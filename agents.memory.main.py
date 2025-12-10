# agents/memory/main.py
import os
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import google.auth
from google.cloud import firestore
from googleapiclient.discovery import build
from google.cloud import aiplatform

app = FastAPI(title="VeriSynthOS Memory Agent")
log = logging.getLogger("memory")
logging.basicConfig(level=logging.INFO)

# GCP setup - optional for development
try:
    credentials, project_id = google.auth.default()
    db = firestore.Client(project=project_id, credentials=credentials)
    log.info("Google Cloud credentials loaded successfully")
except Exception as e:
    log.warning("Google Cloud credentials not found: %s - running in dev mode without GCP", e)
    credentials = None
    project_id = os.getenv("GCP_PROJECT_ID", "verisynthos-dev")
    db = None

# Initialize Vertex AI if credentials available
if credentials:
    aiplatform.init(project=project_id, location=os.getenv("GCP_REGION", "us-central1"))
else:
    log.warning("Vertex AI not initialized - embeddings disabled")

# Embedding model - using aiplatform instead of deprecated vertexai.language_models
embedding_model = None  # Will be initialized when needed

ME_INDEX_ID = os.getenv("ME_INDEX_ID")
ME_ENDPOINT_ID = os.getenv("ME_ENDPOINT_ID")

# Matching Engine - stub for now (requires proper index/endpoint setup)
index = None
endpoint = None

if ME_INDEX_ID and ME_ENDPOINT_ID:
    log.info("Matching Engine configured: index=%s, endpoint=%s", ME_INDEX_ID, ME_ENDPOINT_ID)
else:
    log.warning("ME_INDEX_ID and ME_ENDPOINT_ID not set - vector storage disabled")

# ------------------------------------------------------------------
class IngestRequest(BaseModel):
    folder_id: str | None = None
    gcs_uri: str | None = None
    local_path: str | None = None  # NEW: local file system path
    recursive: bool = True

class SearchRequest(BaseModel):
    query: str
    folder_ids: List[str] = []
    mime_types: List[str] | None = None
    date_from: str | None = None
    top_k: int = 20

# ------------------------------------------------------------------
def sha256_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

def extract_text(file_bytes: bytes, mime: str) -> str:
    # Real production uses PyPDF2, python-docx, google-docs-api, etc.
    # This placeholder is fine for demo — just note it
    return file_bytes.decode("utf-8", errors="ignore")[:500_000]

def semantic_chunk(text: str, max_chars: int = 2800, overlap: int = 560) -> List[Dict[str, Any]]:
    """700-token chunks (~2800 chars) with 20% overlap (560 chars)"""
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunk = text[start:end]
        chunks.append({"text": chunk, "start_char": start})
        start = end - overlap
        if start >= len(text):
            break
    return chunks

def embed(texts: List[str]) -> List[List[float]]:
    """Generate embeddings using Vertex AI text-embedding-004 model."""
    # Use the aiplatform TextEmbeddingModel
    from vertexai.language_models import TextEmbeddingModel
    model = TextEmbeddingModel.from_pretrained("text-embedding-004")
    embeddings = model.get_embeddings([t for t in texts])
    return [e.values for e in embeddings]

# ------------------------------------------------------------------
@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "service": "VeriSynthOS Memory Agent",
        "status": "running",
        "gcp_enabled": credentials is not None,
        "endpoints": ["/", "/health", "/ingest"]
    }

@app.get("/health")
async def health():
    """Detailed health check."""
    return {
        "status": "healthy",
        "gcp_credentials": credentials is not None,
        "firestore": db is not None,
        "matching_engine": ME_INDEX_ID is not None and ME_ENDPOINT_ID is not None
    }

# ------------------------------------------------------------------
# LOCAL FILE SYSTEM INGESTION
# ------------------------------------------------------------------
def process_local_file(filepath: str) -> int:
    """
    Process a local file and store its chunks in Firestore.
    Returns number of chunks stored.
    """
    if not db:
        raise HTTPException(503, "Firestore not initialized - GCP required")
    
    import os
    from pathlib import Path
    
    path = Path(filepath)
    if not path.exists():
        raise HTTPException(404, f"File not found: {filepath}")
    
    # Read file content
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        # Skip binary files
        log.warning(f"Could not read {filepath} as text, skipping")
        return 0
    except Exception as e:
        log.error(f"Error reading {filepath}: {e}")
        return 0
    
    # Generate hash for deduplication
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    
    # Check if already processed
    existing = db.collection("memory_hashes").document(content_hash).get()
    if existing.exists:
        log.info(f"File {filepath} already processed (hash: {content_hash})")
        return 0
    
    # Chunk the content
    chunks = semantic_chunk(content)
    chunk_texts = [c["text"] for c in chunks]
    
    # Try to embed if GCP is available
    embeddings = []
    if credentials:
        try:
            embeddings = embed(chunk_texts)
        except Exception as e:
            log.warning(f"Embedding failed: {e}, storing without vectors")
    
    # Store in Firestore
    file_id = content_hash[:16]
    
    try:
        # Store document metadata
        db.collection("memory_docs").document(file_id).set({
            "file_name": path.name,
            "file_id": file_id,
            "file_path": str(path.absolute()),
            "content_hash": content_hash,
            "modified_time": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            "chunk_count": len(chunks),
            "parent_folder": str(path.parent),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "source": "local"
        })
        
        # Store hash for deduplication
        db.collection("memory_hashes").document(content_hash).set({
            "file_id": file_id,
            "file_name": path.name,
            "indexed_at": datetime.now(timezone.utc).isoformat()
        })
        
        log.info(f"Indexed {len(chunks)} chunks for {path.name}")
    except Exception as e:
        log.error(f"Failed to index {filepath}: {e}")
        return 0
    
    return len(chunks)


def ingest_local_directory(directory: str, recursive: bool = True) -> int:
    """
    Recursively process all text files in a directory.
    Returns total number of chunks stored.
    """
    from pathlib import Path
    
    path = Path(directory)
    if not path.exists() or not path.is_dir():
        raise HTTPException(404, f"Directory not found: {directory}")
    
    total_chunks = 0
    pattern = "**/*" if recursive else "*"
    
    # Supported text file extensions
    text_extensions = {'.txt', '.md', '.py', '.js', '.ts', '.json', '.yaml', '.yml', 
                      '.html', '.css', '.rst', '.tex', '.csv', '.tsv', '.c', '.cpp',
                      '.h', '.hpp', '.java', '.go', '.rs', '.sh', '.bash'}
    
    for file_path in path.glob(pattern):
        if file_path.is_file() and file_path.suffix.lower() in text_extensions:
            try:
                chunks = process_local_file(str(file_path))
                total_chunks += chunks
            except Exception as e:
                log.error(f"Error processing {file_path}: {e}")
                continue
    
    log.info(f"Ingested {total_chunks} total chunks from {directory}")
    return total_chunks


@app.post("/ingest")
async def ingest(req: IngestRequest):
    # Handle local file system ingestion
    if req.local_path:
        if not db:
            raise HTTPException(503, "Firestore not initialized - GCP required for storage")
        
        from pathlib import Path
        path = Path(req.local_path)
        
        if not path.exists():
            raise HTTPException(404, f"Path not found: {req.local_path}")
        
        if path.is_file():
            processed = process_local_file(str(path))
            return {"status": "ok", "files_processed": 1 if processed > 0 else 0, "chunks": processed, "timestamp": datetime.now(timezone.utc).isoformat()}
        elif path.is_dir():
            total_chunks = ingest_local_directory(str(path), req.recursive)
            return {"status": "ok", "directory": str(path), "chunks": total_chunks, "timestamp": datetime.now(timezone.utc).isoformat()}
        else:
            raise HTTPException(400, f"Invalid path: {req.local_path}")
    
    # Handle Google Drive ingestion (requires GCP)
    if not credentials:
        raise HTTPException(503, "GCP credentials not configured - use local_path for local files or configure GCP for Drive ingestion")
    
    if not req.folder_id and not req.gcs_uri:
        raise HTTPException(400, "folder_id, gcs_uri, or local_path required")

    processed = 0
    if req.folder_id:
        drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
        query = f"'{req.folder_id}' in parents and trashed=false"
        files = drive.files().list(q=query, fields="files(id,mimeType,name,modifiedTime,md5Checksum)", pageSize=100).execute().get("files", [])
        for f in files:
            processed += await process_drive_file(f, req.folder_id)
    return {"status": "ok", "files_processed": processed, "timestamp": datetime.now(timezone.utc).isoformat()}

async def process_drive_file(file: Dict[str, Any], parent_folder: str) -> int:
    file_id = file["id"]
    file_name = file["name"]
    modified_time = file["modifiedTime"]

    # Fast dedupe using Drive's built-in md5Checksum (if available)
    if file.get("md5Checksum"):
        content_hash = file["md5Checksum"]
    else:
        # Fallback: download and hash (rare)
        drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
        request = drive.files().get_media(fileId=file_id)
        content = request.execute()
        content_hash = sha256_hash(content)

    if db is None:
        raise RuntimeError("Firestore client (db) is not initialized. Check GCP credentials.")
    if db.collection("memory_hashes").document(content_hash).get().exists:
        log.info("Duplicate skipped (hash match): %s", file_name)
        return 0

    # Download full content
    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
    request = drive.files().get_media(fileId=file_id)
    content = request.execute()

    text = extract_text(content, file.get("mimeType", ""))
    chunks = semantic_chunk(text)

    embeddings = embed([c["text"] for c in chunks])

    datapoints = []
    for i, (chunk, vec) in enumerate(zip(chunks, embeddings)):
        dp_id = f"{file_id}_{i}_{content_hash[:8]}"
        metadata = {
            "source": "drive",
            "file_id": file_id,
            "file_name": file_name,
            "drive_link": f"https://drive.google.com/file/d/{file_id}",
            "revision_id": file.get("headRevisionId"),
            "version_hash": content_hash,
            "page": (i // 4) + 1,
            "chunk_index": i,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "parent_folder": parent_folder
        }
        datapoints.append({"id": dp_id, "embedding": vec, "metadata": metadata, "restrict": ["memory_hashes"]})

    if datapoints:
        try:
            if index is None:
                raise RuntimeError("Matching Engine index is not initialized.")
            if hasattr(index, "upsert_datapoints"):
                index.upsert_datapoints(datapoints)
            else:
                raise AttributeError("Matching Engine index does not support upsert_datapoints.")
            if db is None:
                raise RuntimeError("Firestore client (db) is not initialized. Check GCP credentials.")
            db.collection("memory_docs").document(file_id).set({
                "file_name": file_name,
                "file_id": file_id,
                "content_hash": content_hash,
                "modified_time": modified_time,
                "chunk_count": len(chunks),
                "parent_folder": parent_folder,
                "indexed_at": datetime.now(timezone.utc).isoformat()
            })
            if db is None:
                raise RuntimeError("Firestore client (db) is not initialized. Check GCP credentials.")
            db.collection("memory_hashes").document(content_hash).set({
                "file_id": file_id,
                "file_name": file_name,
                "indexed_at": datetime.now(timezone.utc).isoformat()
            })
            log.info("Indexed %d chunks for %s", len(chunks), file_name)
        except Exception as e:
            log.error("Failed to index %s: %s", file_name, e)
            return 0

    return 1
