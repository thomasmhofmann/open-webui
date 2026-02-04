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
        # Check for Antora structure
        if "/modules/" not in file_path:
            return None
        
        # Split at /modules/ to get the module and page parts
        parts = file_path.split("/modules/")
        if len(parts) != 2:
            return None
        
        module_and_page = parts[1]
        
        # Check for /pages/ directory
        if "/pages/" not in module_and_page:
            return None
        
        # Split at /pages/ to get module name and page path
        module_parts = module_and_page.split("/pages/")
        if len(module_parts) != 2:
            return None
        
        module_name = module_parts[0]
        page_path = module_parts[1]
        
        # Convert .adoc extension to .html
        if page_path.endswith(".adoc"):
            page_path = page_path[:-5] + ".html"
        
        # Build the final URL
        url = f"{base_url.rstrip('/')}/{module_name}/{page_path}"
        return url
    except Exception as e:
        log.debug(f"Error reconstructing URL from path {file_path}: {e}")
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
        # Guard clause: validate file_id and kb_id
        file_id = metadata.get("file_id")
        if not file_id or not kb_id:
            return metadata
        
        # Guard clause: check KB has URL mapping
        if kb_id not in kb_doc_url_mapping:
            return metadata
        
        # Guard clause: validate base_url
        base_url = kb_doc_url_mapping[kb_id]
        if not base_url or not isinstance(base_url, str):
            log.warning(f"Invalid base_url for kb_id {kb_id}: {base_url}")
            return metadata
        
        # Get file path from database
        file_path = get_file_path_from_db(file_id)
        if not file_path:
            return metadata
        
        # Reconstruct external URL
        doc_url = reconstruct_antora_url(file_path, base_url)
        if not doc_url:
            return metadata
        
        # Apply enrichment
        metadata["source"] = doc_url
        metadata.pop("file_id", None)
        
        log.debug(f"Enriched metadata with URL: {doc_url}")
        return metadata
        
    except Exception as e:
        log.warning(
            f"Error enriching metadata: {e}",
            extra={"file_id": metadata.get("file_id"), "kb_id": kb_id}
        )
        return metadata

# Made with Bob
