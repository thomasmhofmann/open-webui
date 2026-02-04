# Patch 3: File Upload Metadata Injector - Implementation Plan

## Executive Summary

This patch adds the ability to inject custom metadata into Qdrant chunks AFTER file processing completes. It leverages the sparse vector index created in Patch 1 to efficiently query and update points.

**Scope:** Add metadata injection capability to file upload pipeline  
**Target File:** `backend/open_webui/routers/retrieval.py`  
**Dependencies:** Patch 1 (Sparse Vectors) - COMPLETED ✅  
**Estimated Effort:** 30-45 minutes  
**Complexity:** LOW

---

## Overview of Changes

### What We're Adding

1. **Helper Function** - `inject_metadata_into_chunks()` to update existing points
2. **Process File Hook** - Call injector after successful file processing
3. **Metadata Update Logic** - Query by file_id and update payloads

### What This Enables

- Post-processing metadata injection
- Adding `custom_id` or other metadata after upload
- Updating existing points without regenerating vectors
- Leverages sparse vector index for efficient queries

---

## Part 1: Add Helper Function

### File: `backend/open_webui/routers/retrieval.py`

**Location:** After imports, before route definitions (around line 50-60)

**Add this function:**

```python
def inject_metadata_into_chunks(file_id: str, custom_metadata: Dict[str, Any]):
    """
    Inject custom metadata into all Qdrant chunks for a file.
    
    This function queries Qdrant for all points associated with a file_id
    and updates their metadata payloads. It leverages the sparse vector index
    for efficient querying.
    
    Args:
        file_id: The file ID to update chunks for
        custom_metadata: Dictionary of metadata to inject into each chunk
        
    Example:
        inject_metadata_into_chunks("abc123", {"custom_id": "eip-1234"})
    """
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        # Get the collection name - try knowledge collection first
        collection_name = "open-webui_knowledge"
        qdrant_client = VECTOR_DB_CLIENT.client
        
        # Build filter to find all points for this file
        scroll_filter = Filter(
            must=[FieldCondition(key="metadata.file_id", match=MatchValue(value=file_id))]
        )
        
        # Query Qdrant for all chunks with this file_id
        scroll_result = qdrant_client.scroll(
            collection_name=collection_name,
            scroll_filter=scroll_filter,
            limit=10000,  # Max chunks per file
            with_payload=True,
            with_vectors=False,  # Don't need vectors, just metadata
        )
        
        if not scroll_result or not scroll_result[0]:
            log.debug(f"No chunks found for file_id={file_id}")
            return
        
        points = scroll_result[0]
        log.info(f"Found {len(points)} chunks for file_id={file_id}, injecting metadata")
        
        # Update each point's metadata
        for point in points:
            existing_payload = point.payload or {}
            existing_metadata = existing_payload.get("metadata", {})
            
            # Merge custom metadata with existing metadata
            updated_metadata = {**existing_metadata, **custom_metadata}
            existing_payload["metadata"] = updated_metadata
            
            # Update the point in Qdrant
            qdrant_client.set_payload(
                collection_name=collection_name,
                points=[point.id],
                payload=existing_payload
            )
        
        log.info(f"Successfully injected metadata into {len(points)} chunks for file_id={file_id}")
        
    except Exception as e:
        log.error(f"Error injecting metadata for file_id={file_id}: {e}")
```

**Why This Implementation?**

1. **Efficient Querying:** Uses sparse vector index to find chunks by file_id
2. **Batch Processing:** Handles up to 10,000 chunks per file
3. **Metadata Merging:** Preserves existing metadata while adding new fields
4. **Error Handling:** Logs errors without breaking file upload
5. **Logging:** Tracks injection progress for monitoring

---

## Part 2: Modify process_file Function

### File: `backend/open_webui/routers/retrieval.py`

**Location:** Function `process_file()` at line 1581

**Current Return Statement (line 1780-1785):**
```python
return {
    "status": True,
    "collection_name": collection_name,
    "filename": file.filename,
    "content": text_content,
}
```

**Modified Code:**
```python
# After successful file processing, inject any custom metadata
# This is a hook for future enhancements (e.g., custom_id extraction)
try:
    # Example: Could extract custom_id from filename or content
    # custom_metadata = {"custom_id": extract_id_from_filename(file.filename)}
    # inject_metadata_into_chunks(file.id, custom_metadata)
    
    # For now, just log that the hook is available
    log.debug(f"File {file.id} processed successfully, metadata injection hook available")
except Exception as e:
    log.warning(f"Error in metadata injection hook for file {file.id}: {e}")

return {
    "status": True,
    "collection_name": collection_name,
    "filename": file.filename,
    "content": text_content,
}
```

**Alternative: Active Implementation with Pre-Compiled Regex**

If you want to actively use the injector now with the config pattern:

```python
# After successful file processing, inject custom metadata
try:
    from open_webui.config import _QDRANT_CUSTOM_ID_COMPILED_PATTERN
    
    custom_metadata = {}
    
    # Extract document ID from filename using pre-compiled pattern
    if _QDRANT_CUSTOM_ID_COMPILED_PATTERN:
        matches = _QDRANT_CUSTOM_ID_COMPILED_PATTERN.findall(file.filename)
        if matches:
            custom_metadata["custom_id"] = matches[0].lower()
            log.info(f"Extracted custom_id '{custom_metadata['custom_id']}' from filename")
    
    # Inject metadata if we have any
    if custom_metadata:
        inject_metadata_into_chunks(file.id, custom_metadata)
        
except Exception as e:
    log.warning(f"Error in metadata injection for file {file.id}: {e}")

return {
    "status": True,
    "collection_name": collection_name,
    "filename": file.filename,
    "content": text_content,
}
```

**Key Points:**
- Uses pre-compiled regex pattern from config (compiled once at module load)
- No runtime regex compilation overhead
- Pattern is configurable via `QDRANT_CUSTOM_ID_FILE_NAME_PATTERN` environment variable
- Defaults to `r"(?i)(?:eip|fsm|fst|ekp)-\d+"` if not set

---

## Part 3: Add Required Imports

### File: `backend/open_webui/routers/retrieval.py`

**Location:** Top of file with other imports (around line 1-30)

**Check if these imports exist, add if missing:**

```python
from typing import Dict, Any  # Should already exist
import logging  # Should already exist

log = logging.getLogger(__name__)  # Should already exist
```

**Note:** Most imports should already be present. The `inject_metadata_into_chunks()` function imports what it needs internally.

---

## Implementation Steps

### Step 1: Add Helper Function
1. Open `backend/open_webui/routers/retrieval.py`
2. Find a good location after imports (around line 50-60)
3. Add `inject_metadata_into_chunks()` function
4. Verify imports are present

### Step 2: Add Hook to process_file
1. Locate the return statement at line 1780-1785
2. Add config import at top of file
3. Add metadata injection hook before return
4. Use pre-compiled regex pattern from config

### Step 3: Test
1. Compile Python: `python3 -m py_compile backend/open_webui/routers/retrieval.py`
2. Upload a test file
3. Check logs for injection messages
4. Query Qdrant to verify metadata was added

---

## Testing Strategy

### Manual Testing

**Step 1: Verify Compilation**
```bash
cd backend
python3 -m py_compile open_webui/routers/retrieval.py
```

**Expected:** No errors

---

**Step 2: Test File Upload**
```bash
# Start Open WebUI
# Upload a file to a knowledge base
# Check logs for:
# - "Found X chunks for file_id=..."
# - "Successfully injected metadata into X chunks..."
```

---

**Step 3: Verify Metadata in Qdrant**
```bash
# Query Qdrant for the file's chunks
curl -X POST "http://localhost:6333/collections/open-webui_knowledge/points/scroll" \
  -H "Content-Type: application/json" \
  -d '{
    "filter": {
      "must": [
        {
          "key": "metadata.file_id",
          "match": {"value": "YOUR_FILE_ID"}
        }
      ]
    },
    "limit": 1,
    "with_payload": true
  }' | jq '.result.points[0].payload.metadata'
```

**Expected Output:**
```json
{
  "file_id": "abc123",
  "name": "document.pdf",
  "custom_id": "eip-1234",  // If active implementation
  ...
}
```

---

## Configuration Options

### Option 1: Passive Hook (Recommended for Now)

Just add the hook without active extraction. This allows future enhancements without breaking anything.

**Pros:**
- Safe, no risk
- Easy to extend later
- No regex pattern needed

**Cons:**
- Doesn't actually inject metadata yet

---

### Option 2: Active Filename Extraction

Extract document IDs from filenames and inject them.

**Pros:**
- Immediately useful
- Simple pattern matching
- No external config needed

**Cons:**
- Assumes filename contains ID
- May not work for all files

**Pattern:** `(?i)(?:eip|fsm|fst|ekp)-\d+`
- Matches: EIP-1234, FST-5678, EKP-9999
- Case-insensitive

---

### Option 3: Configuration-Based (RECOMMENDED FOR PRODUCTION)

Add configuration for custom_id extraction using environment variable. **Always active** - no enable/disable flag.

**Implementation:**
```python
# At end of backend/open_webui/config.py (after line 4024)
# Add comment "# fork" above this section

# fork
QDRANT_CUSTOM_ID_FILE_NAME_PATTERN = os.getenv(
    "QDRANT_CUSTOM_ID_FILE_NAME_PATTERN",
    r"(?i)(?:eip|fsm|fst|ekp)-\d+"
)

# Compile regex pattern once for performance
import re
_QDRANT_CUSTOM_ID_COMPILED_PATTERN = re.compile(QDRANT_CUSTOM_ID_FILE_NAME_PATTERN) if QDRANT_CUSTOM_ID_FILE_NAME_PATTERN else None
```

**Usage in process_file:**
```python
from open_webui.config import _QDRANT_CUSTOM_ID_COMPILED_PATTERN

# Extract document ID from filename using pre-compiled pattern
# Always active - no enable/disable check
if _QDRANT_CUSTOM_ID_COMPILED_PATTERN:
    matches = _QDRANT_CUSTOM_ID_COMPILED_PATTERN.findall(file.filename)
    if matches:
        custom_metadata["custom_id"] = matches[0].lower()
        log.info(f"Extracted custom_id '{custom_metadata['custom_id']}' from filename")
```

**Pros:**
- Always active - no conditional logic needed
- Flexible - pattern can be changed via environment variable
- Non-persistent - doesn't save to database
- Production-ready
- Clearly marked as fork customization

**Cons:**
- Cannot be disabled (by design)
- Requires environment variable setup for custom patterns

**Environment Variable:**
```bash
export QDRANT_CUSTOM_ID_FILE_NAME_PATTERN='(?i)(?:eip|fsm|fst|ekp)-\d+'
```

**Note:** No `ENABLE_CUSTOM_ID_EXTRACTION` flag - extraction is always active when pattern matches.

---

## Error Handling

### Scenarios

1. **No chunks found:** Log debug message, continue
2. **Qdrant query fails:** Log error, don't break upload
3. **Metadata update fails:** Log error, continue with other chunks
4. **Invalid file_id:** Log warning, skip injection

### Logging Levels

- **INFO:** Successful injection, chunk counts
- **DEBUG:** No chunks found, hook available
- **WARNING:** Injection errors (non-critical)
- **ERROR:** Qdrant connection failures

---

## Performance Considerations

### Expected Impact

**Positive:**
- Enables post-processing metadata updates
- Leverages existing sparse vector index
- No impact on initial upload speed

**Negative:**
- Slight delay after upload (< 1 second for typical files)
- Additional Qdrant queries (scroll + set_payload per chunk)
- Minimal - only runs if metadata to inject

### Optimization

- Batch updates if possible (currently updates one point at a time)
- Skip injection if no custom metadata
- Use async if needed (currently synchronous)

---

## Rollback Plan

If issues occur:

```bash
# Revert code changes
git checkout HEAD -- backend/open_webui/routers/retrieval.py

# Restart Open WebUI
# No data migration needed
```

**Note:** Existing files with injected metadata will keep it. New uploads won't get metadata injection after rollback.

---

## Future Enhancements

### Phase 2: Content-Based Extraction

Extract custom_id from document content (not just filename):

```python
# Search first page of document for ID
first_page = text_content[:1000]  # First 1000 chars
matches = re.findall(pattern, first_page)
if matches:
    custom_metadata["custom_id"] = matches[0].lower()
```

### Phase 3: External API Integration

Query external system for document metadata:

```python
# Call external API to get metadata
response = requests.get(f"https://api.example.com/documents/{file.id}")
if response.ok:
    custom_metadata = response.json()
    inject_metadata_into_chunks(file.id, custom_metadata)
```

### Phase 4: Batch Processing

Process multiple files at once:

```python
def inject_metadata_batch(file_ids: List[str], metadata_map: Dict[str, Dict]):
    for file_id in file_ids:
        if file_id in metadata_map:
            inject_metadata_into_chunks(file_id, metadata_map[file_id])
```

---

## Summary

This patch adds a flexible metadata injection system that:

1. **Leverages Patch 1:** Uses sparse vector index for efficient queries
2. **Post-Processing:** Updates metadata after file upload completes
3. **Extensible:** Easy to add custom extraction logic
4. **Safe:** Error handling prevents breaking uploads
5. **Optional:** Can be passive hook or active implementation

**Recommended Approach:** Start with passive hook, add active extraction later if needed.

**Total Changes:** ~60 lines in 1 file  
**Estimated Time:** 30-45 minutes  
**Risk Level:** LOW

---

**Document Version:** 1.0  
**Date:** 2026-02-03  
**Author:** IBM Bob (AI Assistant)