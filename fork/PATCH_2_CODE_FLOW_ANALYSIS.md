# Patch 2: Source Enrichment - Code Flow Analysis

## Executive Summary

After analyzing the codebase, I've identified **THREE distinct code paths** where citation sources are generated and need URL enrichment:

1. **Tool-based RAG Flow** (Native Function Calling) - `get_citation_source_from_tool_result()`
2. **Legacy RAG Flow** (File Attachments) - `get_sources_from_items()`
3. **Direct Document Retrieval** - `retrieve_document_by_custom_id()` (already returns full documents)

**Key Finding:** We need to patch **TWO locations** (paths 1 and 2). Path 3 doesn't need patching as it returns full documents, not citations.

---

## Code Path 1: Tool-Based RAG Flow (Native Function Calling)

### Entry Point
**File:** `backend/open_webui/utils/middleware.py`  
**Function:** `get_citation_source_from_tool_result()` (line 149)

### Flow Description
This is the **modern RAG flow** used when LLMs call builtin tools via native function calling:

```
User Query → LLM decides to call tool → Tool executes → Tool returns JSON result
→ get_citation_source_from_tool_result() converts result to citation format
→ Citations displayed in UI
```

### Current Implementation

```python
def get_citation_source_from_tool_result(
    tool_name: str, tool_params: dict, tool_result: str, tool_id: str = ""
) -> list[dict]:
    """Parse tool result and convert to source dicts for citation display."""
    
    if tool_name == "query_knowledge_files":
        chunks = json.loads(tool_result)
        
        # Group chunks by file_id
        sources_by_file = {}
        for chunk in chunks:
            source_name = chunk.get("source", "Unknown")
            file_id = chunk.get("file_id", "")
            note_id = chunk.get("note_id", "")
            chunk_type = chunk.get("type", "file")
            content = chunk.get("content", "")
            
            key = file_id or note_id or source_name
            
            if key not in sources_by_file:
                sources_by_file[key] = {
                    "source": {
                        "id": file_id or note_id,
                        "name": source_name,
                        "type": chunk_type,
                    },
                    "document": [],
                    "metadata": [],
                }
            
            sources_by_file[key]["document"].append(content)
            sources_by_file[key]["metadata"].append({
                "file_id": file_id,
                "name": source_name,
                "source": source_name,  # ← Currently filename
                **({"note_id": note_id} if note_id else {}),
            })
        
        return list(sources_by_file.values())
    
    elif tool_name == "view_knowledge_file":
        # Returns full document, not chunks
        file_data = json.loads(tool_result)
        return [{
            "source": {...},
            "document": [file_data.get("content", "")],
            "metadata": [{
                "file_id": file_id,
                "name": filename,
                "source": filename,  # ← Currently filename
                ...
            }]
        }]
```

### What Needs to Change

**For `query_knowledge_files` results:**
1. After grouping chunks by file, we have `file_id` and `kb_id` (from Patch 4)
2. Need to check if `kb_id` exists in `KB_DOC_URL_MAPPING`
3. If yes, look up file path from Files table
4. Reconstruct Antora URL from path
5. Replace `metadata["source"]` with external URL
6. Remove `file_id` and `kb_id` from metadata (so UI treats as external link)

**For `view_knowledge_file` results:**
1. Similar logic but for full document view
2. Extract `file_id` and `knowledge_id` from result
3. Convert `knowledge_id` to `kb_id` format
4. Apply same URL reconstruction

---

## Code Path 2: Legacy RAG Flow (File Attachments)

### Entry Point
**File:** `backend/open_webui/retrieval/utils.py`  
**Function:** `get_sources_from_items()` (line 934)

### Flow Description
This is the **legacy RAG flow** used when users attach files/collections to chat:

```
User attaches file/collection → get_sources_from_items() queries vector DB
→ Returns sources with metadata → Citations displayed in UI
```

### Current Implementation

The function handles multiple item types (file, collection, note, chat, url, text) and returns sources in this format:

```python
async def get_sources_from_items(request, items, queries, ...):
    # ... process each item type ...
    
    sources = []
    for query_result in query_results:
        if "documents" in query_result:
            if "metadatas" in query_result:
                source = {
                    "source": query_result["file"],  # Item info
                    "document": query_result["documents"][0],  # Chunk contents
                    "metadata": query_result["metadatas"][0],  # Chunk metadata
                }
                sources.append(source)
    
    return sources
```

### Metadata Structure

For file/collection items, metadata looks like:
```python
{
    "file_id": "abc-123",
    "name": "document.adoc",
    "source": "document.adoc",  # ← Currently filename
}
```

### What Needs to Change

**After line 1205** (where sources are built):
1. For each source in sources list
2. For each metadata entry in source["metadata"]
3. Extract `file_id` from metadata
4. Look up file in Files table to get `collection_name`
5. Convert `collection_name` to `kb_id` (replace underscores with hyphens)
6. Check if `kb_id` in `KB_DOC_URL_MAPPING`
7. If yes, get file path and reconstruct Antora URL
8. Replace `metadata["source"]` with external URL
9. Remove `file_id` from metadata

---

## Code Path 3: Direct Document Retrieval (No Changes Needed)

### Entry Point
**File:** `backend/open_webui/tools/builtin.py`  
**Function:** `retrieve_document_by_custom_id()` (line 1617)

### Why No Changes Needed

This tool returns **full documents**, not citation chunks:

```python
async def retrieve_document_by_custom_id(custom_id: str, ...):
    # 1. Query Qdrant for chunks with custom_id
    # 2. Extract file_ids from chunks
    # 3. Call view_knowledge_file() for each file_id
    # 4. Return complete documents
    
    return json.dumps({
        "custom_id": custom_id,
        "document_count": len(documents),
        "documents": [
            {
                "id": file_id,
                "filename": "...",
                "content": "...",  # Full document content
                "custom_id": custom_id,
                "knowledge_id": kb_id,
                "knowledge_name": kb_name,
            }
        ]
    })
```

**Key Difference:** This returns full document content for the LLM to process, not citation metadata for UI display. The LLM reads the entire document and generates its own response.

**However:** When this tool's result is processed by `get_citation_source_from_tool_result()`, it goes through the `view_knowledge_file` branch, which **does** need URL enrichment (covered in Code Path 1).

---

## Implementation Requirements

### Helper Functions Needed

```python
def get_kb_id_from_file_id(file_id: str) -> Optional[str]:
    """
    Look up file in Files table and extract kb_id from collection_name.
    
    Args:
        file_id: File UUID
        
    Returns:
        kb_id (e.g., "eip-documentation") or None
    """
    file = Files.get_file_by_id(file_id)
    if not file or not file.meta:
        return None
    
    collection_name = file.meta.get("collection_name")
    if not collection_name:
        return None
    
    # Convert collection_name to kb_id (underscores → hyphens)
    kb_id = collection_name.replace("_", "-")
    return kb_id


def get_file_path_from_db(file_id: str) -> Optional[str]:
    """
    Get file path from Files table.
    
    Args:
        file_id: File UUID
        
    Returns:
        File path or None
    """
    file = Files.get_file_by_id(file_id)
    if not file or not file.meta:
        return None
    
    return file.meta.get("path")


def reconstruct_antora_url(file_path: str, base_url: str) -> Optional[str]:
    """
    Reconstruct Antora documentation URL from file path.
    
    Args:
        file_path: e.g., "com.ibm.eip.docs/modules/quality/pages/overview.adoc"
        base_url: e.g., "https://docs.example.com/eip"
        
    Returns:
        URL: e.g., "https://docs.example.com/eip/quality/overview.html"
        or None if path doesn't match Antora structure
    """
    # Find "modules" in path
    if "/modules/" not in file_path:
        return None
    
    # Extract module name and page path
    # Pattern: .../modules/{module}/pages/{page}.adoc
    parts = file_path.split("/modules/")
    if len(parts) != 2:
        return None
    
    module_and_page = parts[1]
    
    # Find "pages" directory
    if "/pages/" not in module_and_page:
        return None
    
    module_parts = module_and_page.split("/pages/")
    if len(module_parts) != 2:
        return None
    
    module_name = module_parts[0]
    page_path = module_parts[1]
    
    # Convert .adoc to .html
    if page_path.endswith(".adoc"):
        page_path = page_path[:-5] + ".html"
    
    # Build URL
    url = f"{base_url.rstrip('/')}/{module_name}/{page_path}"
    return url


def enrich_metadata_with_url(metadata: dict, kb_doc_url_mapping: dict) -> dict:
    """
    Enrich a single metadata entry with external URL if available.
    
    Args:
        metadata: Metadata dict with file_id, source, etc.
        kb_doc_url_mapping: Dict mapping kb_id → base_url
        
    Returns:
        Enriched metadata dict (modified in place)
    """
    file_id = metadata.get("file_id")
    if not file_id:
        return metadata
    
    # Get kb_id from file
    kb_id = get_kb_id_from_file_id(file_id)
    if not kb_id or kb_id not in kb_doc_url_mapping:
        return metadata
    
    # Get file path
    file_path = get_file_path_from_db(file_id)
    if not file_path:
        return metadata
    
    # Reconstruct URL
    base_url = kb_doc_url_mapping[kb_id]
    doc_url = reconstruct_antora_url(file_path, base_url)
    if not doc_url:
        return metadata
    
    # Replace source with URL and remove file_id
    metadata["source"] = doc_url
    metadata.pop("file_id", None)
    metadata.pop("kb_id", None)  # Remove if present
    
    return metadata
```

### Configuration Needed

**File:** `backend/open_webui/config.py`

```python
# Knowledge Base Documentation URL Mapping
# Maps kb_id to base documentation URL for external link generation
KB_DOC_URL_MAPPING = {
    "eip-documentation": "https://docs.example.com/eip",
    "fsm-documentation": "https://docs.example.com/fsm",
    # Add more mappings as needed
}
```

---

## Patch Locations Summary

### Location 1: `backend/open_webui/utils/middleware.py`

**Function:** `get_citation_source_from_tool_result()` (line 149)

**Modification Point:** After line 256 (in `query_knowledge_files` branch)

```python
elif tool_name == "query_knowledge_files":
    chunks = json.loads(tool_result)
    
    # ... existing grouping logic ...
    
    # NEW: Enrich metadata with URLs
    from open_webui.config import KB_DOC_URL_MAPPING
    
    for source in sources_by_file.values():
        for metadata in source.get("metadata", []):
            enrich_metadata_with_url(metadata, KB_DOC_URL_MAPPING)
    
    return list(sources_by_file.values())
```

**Also modify:** `view_knowledge_file` branch (line 191) similarly

### Location 2: `backend/open_webui/retrieval/utils.py`

**Function:** `get_sources_from_items()` (line 934)

**Modification Point:** After line 1205 (where sources are built)

```python
sources = []
for query_result in query_results:
    try:
        if "documents" in query_result:
            if "metadatas" in query_result:
                source = {
                    "source": query_result["file"],
                    "document": query_result["documents"][0],
                    "metadata": query_result["metadatas"][0],
                }
                
                # NEW: Enrich metadata with URLs
                from open_webui.config import KB_DOC_URL_MAPPING
                for metadata in source["metadata"]:
                    enrich_metadata_with_url(metadata, KB_DOC_URL_MAPPING)
                
                sources.append(source)
    except Exception as e:
        log.exception(e)

return sources
```

---

## Testing Strategy

### Test Case 1: Tool-Based RAG
1. Enable native function calling
2. Ask: "What is in EIP-1234?"
3. LLM calls `query_knowledge_files()`
4. Verify citations show external URLs, not filenames

### Test Case 2: Legacy RAG
1. Attach a knowledge base to chat
2. Ask a question
3. Verify citations show external URLs, not filenames

### Test Case 3: Direct Retrieval
1. Ask: "Show me EIP-1234"
2. LLM calls `retrieve_document_by_custom_id()`
3. Result goes through `view_knowledge_file` branch
4. Verify any citations show external URLs

### Test Case 4: No Mapping
1. Use a KB not in `KB_DOC_URL_MAPPING`
2. Verify citations still work (show filenames as fallback)

---

## Risk Assessment

### Low Risk
- Helper functions are pure and isolated
- Changes are additive (don't break existing behavior)
- Fallback to filename if URL reconstruction fails

### Medium Risk
- Need to handle Files table lookups efficiently
- Should cache file metadata to avoid N queries

### Mitigation
- Add error handling in all helper functions
- Log failures but don't crash
- Consider caching file metadata lookups

---

## Dependencies

### From Patch 4 (Already Implemented)
- `kb_id` field in chunks from `query_knowledge_files()`
- This enables efficient URL enrichment without extra DB queries

### New Dependencies
- `KB_DOC_URL_MAPPING` configuration
- Helper functions for URL reconstruction
- Files table access for path lookup

---

## Next Steps

1. ✅ Code flow analysis complete
2. ⏭️ Create detailed implementation plan
3. ⏭️ Implement helper functions
4. ⏭️ Patch Location 1 (middleware.py)
5. ⏭️ Patch Location 2 (retrieval/utils.py)
6. ⏭️ Add configuration
7. ⏭️ Test all code paths
8. ⏭️ Document changes