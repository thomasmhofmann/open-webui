# Patch 2: Source Enrichment - Implementation Plan

## Overview

This plan implements URL enrichment for citation sources, replacing internal filenames with external documentation URLs. Based on the code flow analysis, we need to patch **two locations** where citation metadata is generated.

---

## Implementation Steps

### Step 1: Add Configuration (config.py)

**File:** `backend/open_webui/config.py`  
**Location:** After existing configuration sections (around line 4040)

**Action:** Add KB documentation URL mapping configuration

```python
####################################
# Knowledge Base URL Mapping
####################################

# fork: Maps knowledge base IDs to external documentation base URLs
# Used to replace internal file paths with external documentation links in citations
KB_DOC_URL_MAPPING = {
    # Example mappings (customize for your deployment):
    # "eip-documentation": "https://docs.example.com/eip",
    # "fsm-documentation": "https://docs.example.com/fsm",
}

# Allow override from environment variable (JSON format)
if KB_DOC_URL_MAPPING_ENV := os.environ.get("KB_DOC_URL_MAPPING"):
    try:
        KB_DOC_URL_MAPPING = json.loads(KB_DOC_URL_MAPPING_ENV)
    except json.JSONDecodeError:
        log.warning("Invalid KB_DOC_URL_MAPPING environment variable, using default")
```

**Rationale:**
- Centralized configuration for URL mappings
- Supports environment variable override for deployment flexibility
- Empty default (no URLs) ensures backward compatibility
- Marked with `# fork` comment for tracking

---

### Step 2: Add Helper Functions (utils/middleware.py)

**File:** `backend/open_webui/utils/middleware.py`  
**Location:** After imports, before existing functions (around line 60)

**Action:** Add URL reconstruction helper functions

```python
####################################
# Source Enrichment Helpers
####################################

def get_kb_id_from_file_id(file_id: str) -> Optional[str]:
    """
    Look up file in Files table and extract kb_id from collection_name.
    
    Args:
        file_id: File UUID
        
    Returns:
        kb_id (e.g., "eip-documentation") or None
    """
    try:
        from open_webui.models.files import Files
        
        file = Files.get_file_by_id(file_id)
        if not file or not file.meta:
            return None
        
        collection_name = file.meta.get("collection_name")
        if not collection_name:
            return None
        
        # Convert collection_name to kb_id (underscores → hyphens)
        kb_id = collection_name.replace("_", "-")
        return kb_id
    except Exception as e:
        log.debug(f"Error getting kb_id for file {file_id}: {e}")
        return None


def get_file_path_from_db(file_id: str) -> Optional[str]:
    """
    Get file path from Files table.
    
    Args:
        file_id: File UUID
        
    Returns:
        File path or None
    """
    try:
        from open_webui.models.files import Files
        
        file = Files.get_file_by_id(file_id)
        if not file or not file.meta:
            return None
        
        return file.meta.get("path")
    except Exception as e:
        log.debug(f"Error getting path for file {file_id}: {e}")
        return None


def reconstruct_antora_url(file_path: str, base_url: str) -> Optional[str]:
    """
    Reconstruct Antora documentation URL from file path.
    
    Antora structure: .../modules/{module}/pages/{page}.adoc
    Output URL: {base_url}/{module}/{page}.html
    
    Args:
        file_path: e.g., "com.ibm.eip.docs/modules/quality/pages/overview.adoc"
        base_url: e.g., "https://docs.example.com/eip"
        
    Returns:
        URL: e.g., "https://docs.example.com/eip/quality/overview.html"
        or None if path doesn't match Antora structure
    """
    try:
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
    except Exception as e:
        log.debug(f"Error reconstructing URL from path {file_path}: {e}")
        return None


def enrich_metadata_with_url(metadata: dict, kb_doc_url_mapping: dict) -> dict:
    """
    Enrich a single metadata entry with external URL if available.
    
    Modifies metadata in place:
    - Replaces metadata["source"] with external URL
    - Removes metadata["file_id"] (so UI treats as external link)
    - Removes metadata["kb_id"] if present
    
    Args:
        metadata: Metadata dict with file_id, source, etc.
        kb_doc_url_mapping: Dict mapping kb_id → base_url
        
    Returns:
        Enriched metadata dict (same object, modified in place)
    """
    try:
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
        
        # Replace source with URL and remove internal IDs
        metadata["source"] = doc_url
        metadata.pop("file_id", None)
        metadata.pop("kb_id", None)
        
        log.debug(f"Enriched metadata with URL: {doc_url}")
        return metadata
    except Exception as e:
        log.debug(f"Error enriching metadata: {e}")
        return metadata
```

**Rationale:**
- Pure functions with clear single responsibilities
- Comprehensive error handling (log but don't crash)
- Returns None on failure (graceful degradation)
- Modifies metadata in place for efficiency
- Supports Antora documentation structure (common in enterprise docs)

---

### Step 3: Patch Location 1 - Tool-Based RAG (middleware.py)

**File:** `backend/open_webui/utils/middleware.py`  
**Function:** `get_citation_source_from_tool_result()` (line 149)

#### Patch 3a: query_knowledge_files branch

**Location:** After line 256 (end of query_knowledge_files processing)

**Current code:**
```python
elif tool_name == "query_knowledge_files":
    chunks = json.loads(tool_result)
    
    # Group chunks by source for better citation display
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
        sources_by_file[key]["metadata"].append(
            {
                "file_id": file_id,
                "name": source_name,
                "source": source_name,
                **({"note_id": note_id} if note_id else {}),
            }
        )
    
    # Return all grouped sources as a list
    if sources_by_file:
        return list(sources_by_file.values())
```

**Add after line 256 (before the return statement):**
```python
    # Return all grouped sources as a list
    if sources_by_file:
        # fork: Enrich metadata with external URLs if available
        from open_webui.config import KB_DOC_URL_MAPPING
        
        if KB_DOC_URL_MAPPING:
            for source in sources_by_file.values():
                for metadata in source.get("metadata", []):
                    enrich_metadata_with_url(metadata, KB_DOC_URL_MAPPING)
        
        return list(sources_by_file.values())
```

#### Patch 3b: view_knowledge_file branch

**Location:** After line 217 (end of view_knowledge_file processing)

**Current code:**
```python
elif tool_name == "view_knowledge_file":
    file_data = json.loads(tool_result)
    filename = file_data.get("filename", "Unknown File")
    file_id = file_data.get("id", "")
    knowledge_name = file_data.get("knowledge_name", "")
    
    return [
        {
            "source": {
                "id": file_id,
                "name": filename,
                "type": "file",
            },
            "document": [file_data.get("content", "")],
            "metadata": [
                {
                    "file_id": file_id,
                    "name": filename,
                    "source": filename,
                    **(
                        {"knowledge_name": knowledge_name}
                        if knowledge_name
                        else {}
                    ),
                }
            ],
        }
    ]
```

**Replace with:**
```python
elif tool_name == "view_knowledge_file":
    file_data = json.loads(tool_result)
    filename = file_data.get("filename", "Unknown File")
    file_id = file_data.get("id", "")
    knowledge_name = file_data.get("knowledge_name", "")
    
    metadata = {
        "file_id": file_id,
        "name": filename,
        "source": filename,
        **(
            {"knowledge_name": knowledge_name}
            if knowledge_name
            else {}
        ),
    }
    
    # fork: Enrich metadata with external URL if available
    from open_webui.config import KB_DOC_URL_MAPPING
    
    if KB_DOC_URL_MAPPING:
        enrich_metadata_with_url(metadata, KB_DOC_URL_MAPPING)
    
    return [
        {
            "source": {
                "id": file_id,
                "name": filename,
                "type": "file",
            },
            "document": [file_data.get("content", "")],
            "metadata": [metadata],
        }
    ]
```

**Rationale:**
- Enriches URLs for both tool result types
- Only processes if KB_DOC_URL_MAPPING is configured
- Graceful fallback to filename if enrichment fails
- Minimal code changes (additive only)

---

### Step 4: Patch Location 2 - Legacy RAG (retrieval/utils.py)

**File:** `backend/open_webui/retrieval/utils.py`  
**Function:** `get_sources_from_items()` (line 934)  
**Location:** After line 1205 (where sources are built)

**Current code:**
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
                if "distances" in query_result and query_result["distances"]:
                    source["distances"] = query_result["distances"][0]
                
                sources.append(source)
    except Exception as e:
        log.exception(e)
return sources
```

**Replace with:**
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
                if "distances" in query_result and query_result["distances"]:
                    source["distances"] = query_result["distances"][0]
                
                # fork: Enrich metadata with external URLs if available
                from open_webui.config import KB_DOC_URL_MAPPING
                from open_webui.utils.middleware import enrich_metadata_with_url
                
                if KB_DOC_URL_MAPPING:
                    for metadata in source["metadata"]:
                        enrich_metadata_with_url(metadata, KB_DOC_URL_MAPPING)
                
                sources.append(source)
    except Exception as e:
        log.exception(e)
return sources
```

**Rationale:**
- Enriches URLs for legacy file attachment flow
- Imports helper function from middleware
- Only processes if KB_DOC_URL_MAPPING is configured
- Preserves existing error handling

---

## Testing Plan

### Test 1: Tool-Based RAG with URL Mapping

**Setup:**
1. Configure KB_DOC_URL_MAPPING in config.py
2. Upload Antora-structured documents to knowledge base
3. Enable native function calling

**Test:**
```
User: "What is in the quality management documentation?"
Expected: LLM calls query_knowledge_files()
Verify: Citations show external URLs (e.g., https://docs.example.com/eip/quality/overview.html)
```

### Test 2: Legacy RAG with URL Mapping

**Setup:**
1. Same configuration as Test 1
2. Attach knowledge base to chat (legacy mode)

**Test:**
```
User: "Tell me about quality management"
Expected: get_sources_from_items() queries vector DB
Verify: Citations show external URLs
```

### Test 3: No URL Mapping (Backward Compatibility)

**Setup:**
1. Empty KB_DOC_URL_MAPPING (default)
2. Upload documents to knowledge base

**Test:**
```
User: "What is in the documentation?"
Expected: Normal RAG flow
Verify: Citations show filenames (existing behavior)
```

### Test 4: Partial Mapping

**Setup:**
1. Configure mapping for only one KB
2. Query documents from both mapped and unmapped KBs

**Test:**
```
User: "Compare EIP and FSM documentation"
Expected: Mixed results
Verify: 
- EIP citations show URLs (mapped)
- FSM citations show filenames (unmapped)
```

### Test 5: Invalid Path Structure

**Setup:**
1. Configure URL mapping
2. Upload non-Antora documents

**Test:**
```
User: "What is in document.pdf?"
Expected: Normal RAG flow
Verify: Citations show filename (URL reconstruction fails gracefully)
```

### Test 6: view_knowledge_file Tool

**Setup:**
1. Configure URL mapping
2. Enable native function calling

**Test:**
```
User: "Show me the full content of quality-overview.adoc"
Expected: LLM calls view_knowledge_file()
Verify: Citation shows external URL
```

---

## Rollback Plan

If issues arise, rollback is straightforward:

1. **Remove configuration** from config.py (lines added in Step 1)
2. **Remove helper functions** from middleware.py (lines added in Step 2)
3. **Revert patches** in middleware.py (Step 3)
4. **Revert patches** in retrieval/utils.py (Step 4)

All changes are additive and isolated, so removal is clean.

---

## Performance Considerations

### Database Queries

**Concern:** Each metadata enrichment requires 1-2 DB queries (file lookup + path lookup)

**Mitigation:**
1. Only query if KB is in mapping (most KBs won't be)
2. Queries are fast (indexed by file_id)
3. Consider adding caching in future if needed

### Impact Analysis

- **Tool-based RAG:** Typically 1-5 files per query → 2-10 DB queries
- **Legacy RAG:** Typically 5-20 chunks per query → 10-40 DB queries (but grouped by file)
- **Overall:** Negligible impact (<50ms added latency)

---

## Documentation Updates

### User Documentation

Add to knowledge base documentation:

```markdown
## External Documentation Links

Open WebUI can automatically replace internal file paths with external documentation URLs in citations.

### Configuration

Add to your `.env` file:

```bash
KB_DOC_URL_MAPPING='{"eip-documentation": "https://docs.example.com/eip"}'
```

Or configure in `config.py`:

```python
KB_DOC_URL_MAPPING = {
    "eip-documentation": "https://docs.example.com/eip",
    "fsm-documentation": "https://docs.example.com/fsm",
}
```

### Supported Documentation Structures

Currently supports Antora documentation structure:
- Path: `.../modules/{module}/pages/{page}.adoc`
- URL: `{base_url}/{module}/{page}.html`

### Example

With configuration:
```python
KB_DOC_URL_MAPPING = {
    "eip-documentation": "https://docs.example.com/eip"
}
```

File path: `com.ibm.eip.docs/modules/quality/pages/overview.adoc`  
Citation URL: `https://docs.example.com/eip/quality/overview.html`
```

---

## Success Criteria

- ✅ Configuration added to config.py
- ✅ Helper functions added to middleware.py
- ✅ Tool-based RAG enriched (middleware.py)
- ✅ Legacy RAG enriched (retrieval/utils.py)
- ✅ All tests pass
- ✅ No performance degradation
- ✅ Backward compatible (empty mapping = no changes)
- ✅ Documentation updated

---

## Implementation Order

1. **Step 1:** Add configuration (safest, no behavior change)
2. **Step 2:** Add helper functions (pure functions, no side effects)
3. **Step 3:** Patch middleware.py (test tool-based RAG)
4. **Step 4:** Patch retrieval/utils.py (test legacy RAG)
5. **Testing:** Run all test cases
6. **Documentation:** Update user docs

---

## Notes

- All changes marked with `# fork` comment for tracking
- Helper functions use defensive programming (return None on error)
- No breaking changes to existing functionality
- URL enrichment is optional (controlled by configuration)
- Supports gradual rollout (configure one KB at a time)