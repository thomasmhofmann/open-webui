"""
Knowledge Base Utilities

Provides helper functions for working with knowledge bases,
including batch queries, URL reconstruction, and metadata enrichment.
"""

import logging
from typing import Optional, Dict, Set, Any

log = logging.getLogger(__name__)


def get_kb_ids_for_files(file_ids: Set[str]) -> Dict[str, str]:
    """
    Get knowledge base IDs for multiple files in a single batch query.
    
    This function performs a single database query to fetch KB IDs for all
    provided file IDs, which is much more efficient than querying individually.
    
    Originally implemented in builtin.py for Patch 4, moved here to make it
    available as a general utility for source enrichment (Patch 2).
    
    :param file_ids: Set of file IDs to look up
    :return: Dictionary mapping file_id → kb_id (first KB if file is in multiple)
    """
    try:
        from open_webui.models.knowledge import KnowledgeFile
        from open_webui.internal.db import get_db
        
        if not file_ids:
            return {}
        
        with get_db() as db:
            # Single query with IN clause - gets all mappings at once
            results = (
                db.query(KnowledgeFile.file_id, KnowledgeFile.knowledge_id)
                .filter(KnowledgeFile.file_id.in_(file_ids))
                .all()
            )
            
            # Build mapping: file_id → kb_id
            # If file is in multiple KBs, first one wins (consistent behavior)
            kb_map = {}
            for file_id, kb_id in results:
                if file_id not in kb_map:
                    kb_map[file_id] = kb_id
            
            return kb_map
    except Exception as e:
        log.exception(f"Error getting kb_ids for files: {e}")
        return {}


def get_file_path_from_db(file_id: str) -> Optional[str]:
    """
    Get file path from Files table.
    
    The file path is stored in file.meta and is used for reconstructing
    external documentation URLs (e.g., Antora documentation structure).
    
    :param file_id: File UUID
    :return: File path from file.meta or None if not found
    """
    try:
        from open_webui.models.files import Files
        
        log.debug(f"[URL_ENRICH] Looking up file path for file_id: {file_id}")
        file = Files.get_file_by_id(file_id)
        if not file:
            log.debug(f"[URL_ENRICH] File not found for file_id: {file_id}")
            return None
        if not file.meta:
            log.debug(f"[URL_ENRICH] File.meta is None for file_id: {file_id}")
            return None
        
        # Path is stored in file.meta.data.path (confirmed via database query)
        file_meta = file.meta or {}
        log.debug(f"[URL_ENRICH] file.meta keys: {list(file_meta.keys())}")
        
        # Get custom metadata from 'data' field
        custom_metadata = file_meta.get("data")
        log.debug(f"[URL_ENRICH] custom_metadata found: {custom_metadata is not None}")
        
        if custom_metadata and isinstance(custom_metadata, dict):
            path = custom_metadata.get("path")
            if path:
                log.debug(f"[URL_ENRICH] Found path in file.meta.data: {path}")
                return path
        
        log.debug(f"[URL_ENRICH] No 'path' found in file.meta.data for file_id: {file_id}")
        return None
    except Exception as e:
        log.warning(f"[URL_ENRICH] Error getting path for file {file_id}: {e}")
        return None


def reconstruct_antora_url(file_path: str, base_url: str) -> Optional[str]:
    """
    Reconstruct Antora documentation URL from file path.
    
    Antora is a documentation site generator that uses a specific directory structure:
    - Structure: .../modules/{module}/pages/{page}.adoc
    - Output URL: {base_url}/{module}/{page}.html
    
    Example:
        Input:  file_path = "com.ibm.eip.docs/modules/quality/pages/overview.adoc"
                base_url = "https://docs.example.com/eip"
        Output: "https://docs.example.com/eip/quality/overview.html"
    
    :param file_path: File path from file.meta (Antora structure)
    :param base_url: Base URL for the documentation site
    :return: Reconstructed URL or None if path doesn't match Antora structure
    """
    try:
        log.debug(f"[URL_ENRICH] Reconstructing URL from path: {file_path}, base_url: {base_url}")
        
        # Check for Antora structure
        if "/modules/" not in file_path:
            log.debug(f"[URL_ENRICH] Path does not contain '/modules/' - not Antora structure")
            return None
        
        # Split at /modules/ to get the module and page parts
        parts = file_path.split("/modules/")
        if len(parts) != 2:
            log.debug(f"[URL_ENRICH] Path split by '/modules/' did not yield 2 parts: {len(parts)}")
            return None
        
        module_and_page = parts[1]
        log.debug(f"[URL_ENRICH] Module and page part: {module_and_page}")
        
        # Check for /pages/ directory
        if "/pages/" not in module_and_page:
            log.debug(f"[URL_ENRICH] Module part does not contain '/pages/' - not Antora structure")
            return None
        
        # Split at /pages/ to get module name and page path
        module_parts = module_and_page.split("/pages/")
        if len(module_parts) != 2:
            log.debug(f"[URL_ENRICH] Module split by '/pages/' did not yield 2 parts: {len(module_parts)}")
            return None
        
        module_name = module_parts[0]
        page_path = module_parts[1]
        log.debug(f"[URL_ENRICH] Extracted module: {module_name}, page: {page_path}")
        
        # Convert .adoc extension to .html
        if page_path.endswith(".adoc"):
            page_path = page_path[:-5] + ".html"
            log.debug(f"[URL_ENRICH] Converted .adoc to .html: {page_path}")
        
        # Build the final URL
        url = f"{base_url.rstrip('/')}/{module_name}/{page_path}"
        log.info(f"[URL_ENRICH] Successfully reconstructed URL: {url}")
        return url
    except Exception as e:
        log.warning(f"[URL_ENRICH] Error reconstructing URL from path {file_path}: {e}")
        return None


def enrich_metadata_with_url(
    metadata: Dict[str, Any],
    kb_id: str,
    kb_doc_url_mapping: Dict[str, str]
) -> Dict[str, Any]:
    """
    Enrich a single metadata entry with external URL if available.
    
    This function replaces internal file references with external documentation URLs
    for better user experience. When a knowledge base is configured with a base URL,
    citations will link to the external documentation instead of showing internal file paths.
    
    Modifies metadata in place:
    - Replaces metadata["source"] with external URL (if reconstruction succeeds)
    - Removes metadata["file_id"] (so UI treats it as an external link)
    
    If URL reconstruction fails (e.g., non-Antora structure, missing path),
    the metadata is returned unchanged (graceful degradation).
    
    :param metadata: Metadata dict with file_id, source, etc.
    :param kb_id: Knowledge base ID for this file
    :param kb_doc_url_mapping: Dict mapping kb_id → base_url
    :return: Enriched metadata dict (same object, modified in place)
    """
    try:
        log.debug(f"[URL_ENRICH] === Starting enrichment ===")
        log.debug(f"[URL_ENRICH] Input metadata keys: {list(metadata.keys())}")
        log.debug(f"[URL_ENRICH] kb_id: {kb_id}")
        log.debug(f"[URL_ENRICH] kb_doc_url_mapping has {len(kb_doc_url_mapping)} entries")
        
        # Guard clause: validate file_id and kb_id
        file_id = metadata.get("file_id")
        if not file_id:
            log.debug(f"[URL_ENRICH] No file_id in metadata - skipping enrichment")
            return metadata
        if not kb_id:
            log.debug(f"[URL_ENRICH] No kb_id provided - skipping enrichment")
            return metadata
        
        log.debug(f"[URL_ENRICH] file_id: {file_id}")
        
        # Guard clause: check KB has URL mapping
        if kb_id not in kb_doc_url_mapping:
            log.debug(f"[URL_ENRICH] kb_id '{kb_id}' not in KB_DOC_URL_MAPPING - skipping enrichment")
            log.debug(f"[URL_ENRICH] Available KB IDs: {list(kb_doc_url_mapping.keys())}")
            return metadata
        
        # Guard clause: validate base_url
        base_url = kb_doc_url_mapping[kb_id]
        if not base_url or not isinstance(base_url, str):
            log.warning(f"[URL_ENRICH] Invalid base_url for kb_id {kb_id}: {base_url}")
            return metadata
        
        log.debug(f"[URL_ENRICH] Found base_url for kb_id: {base_url}")
        
        # Get file path from database
        file_path = get_file_path_from_db(file_id)
        if not file_path:
            log.debug(f"[URL_ENRICH] No file path found - skipping enrichment")
            return metadata
        
        # Reconstruct external URL
        doc_url = reconstruct_antora_url(file_path, base_url)
        if not doc_url:
            log.debug(f"[URL_ENRICH] URL reconstruction failed - skipping enrichment")
            return metadata
        
        # Apply enrichment
        old_source = metadata.get("source")
        metadata["source"] = doc_url
        metadata.pop("file_id", None)
        
        log.info(f"[URL_ENRICH] ✓ Successfully enriched metadata: '{old_source}' -> '{doc_url}'")
        log.debug(f"[URL_ENRICH] Removed file_id from metadata (will open URL instead of download)")
        return metadata
        
    except Exception as e:
        log.error(
            f"[URL_ENRICH] Exception during enrichment: {e}",
            extra={"file_id": metadata.get("file_id"), "kb_id": kb_id},
            exc_info=True
        )
        return metadata

# Made with Bob
