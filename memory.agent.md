# memory.agent.md
## Purpose
Long-term, versioned, chunked & embedded document memory. The system's permanent hippocampus.

## Responsibilities
- Watch user/org Drive folders and GCS buckets in real time
- On new/change → extract text → semantic chunking (700-token chunks + 20% overlap) → embed → upsert
- Deduplicate by SHA-256 content hash (never re-embed the same document twice)
- Hybrid search: vector + BM25 + metadata filters (folder, date, mime, version, file_id)
- Return exact provenance including Drive revision ID and version history
- Support time-travel queries (“what did we know as of 2025-06-01?”)

## Tools & Permissions
- Google Drive API (`files.watch`, `changes.watch`, `revisions.list`)
- GCS Eventarc → Cloud Run
- Vertex AI Embeddings (`text-embedding-004`)
- Vertex Matching Engine (hybrid dense + sparse indexes)
- Firestore (metadata, hash dedupe, revision tracking)
- Cloud Tasks + exponential backoff for retryable ingestion failures

## API / Tool interface
POST   /ingest    {folder_id | gcs_uri, recursive: bool = true}
GET    /search    {query, folder_ids[], mime_types[], date_from?, date_to?, version_hash?, top_k=20} [TODO: Not yet implemented]
DELETE /doc       {doc_id}   (for compliance — triggers soft-delete + purge from index) [TODO: Not yet implemented]

## Current Implementation Status
✅ **Implemented:**
- POST /ingest endpoint with Drive folder ingestion
- SHA-256 content hash deduplication
- Semantic chunking (700-token chunks with 20% overlap, configured as 2800 chars with 560 char overlap)
- Vertex AI text-embedding-004 embeddings
- Matching Engine index upsert
- Firestore metadata storage (memory_docs and memory_hashes collections)
- Drive file metadata tracking (file_id, file_name, content_hash, modified_time, parent_folder)
- Error handling with logging

⚠️ **Pending Implementation:**
- GET /search endpoint for hybrid vector + metadata search
- DELETE /doc endpoint for compliance
- Real-time Drive folder watching with webhooks
- GCS bucket ingestion support
- Time-travel queries by version_hash
- Cloud Tasks retry mechanism
- Drive watch channel renewal
- Soft-delete with retention window
- Audit trail via provenance_events collection

## Output format (search)
{
  "passages": [
    {
      "text": "…",
      "score": 0.89,
      "provenance": {
        "source": "drive",
        "file_id": "1a2b3cdef...",
        "file_name": "Q3-2025-ESG-Report.pdf",
        "drive_link": "https://drive.google.com/file/d/1a2b3cdef...",
        "revision_id": "rev-7a9b2c1d",          // ← NEW: Drive revision
        "version_hash": "a1b2c3d4e5f6...",     // ← SHA-256 of file content
        "page": 47,
        "chunk_index": 118,
        "uploaded_at": "2025-11-20T14:32:11Z",
        "modified_at": "2025-11-19T09:11:03Z"
      }
    }
  ]
}

## Implementation Notes & Enterprise Hardening
- **Chunking**: Fixed 700-token chunks (approximately 2800 characters) with 140-token (560 character, 20%) overlap to prevent context fragmentation at boundaries.
- **Versioning**: Every ingested file stores Drive metadata and full-file SHA-256 `version_hash` (using Drive's md5Checksum when available, or computing SHA-256 as fallback). Enables exact reproducibility and future time-travel search capability.
- **Deduplication**: Fast content-based deduplication using memory_hashes collection before processing files.
- **Current Architecture**: 
  - FastAPI application with POST /ingest endpoint
  - Google Drive API integration for file retrieval
  - Vertex AI text-embedding-004 for embeddings
  - Vertex Matching Engine for vector storage
  - Firestore for metadata and hash tracking
- **Error Handling**: Basic try-catch with logging in ingestion pipeline. Returns file count on success.
- **Future Enhancements**:
  - Real-time Drive watch channels with automatic renewal
  - GCS Eventarc integration for bucket monitoring
  - Cloud Tasks with exponential backoff for resilient retry
  - Quota-aware rate limiting with channel sharding for high-volume folders
  - Horizontal scaling with distributed lease locks
  - Soft-delete + 30-day retention compliance
  - Full audit trail via provenance_events collection
