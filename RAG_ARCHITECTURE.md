# VeriSynthOS RAG Architecture

## How Document Ingestion Works

### Local File System Flow

```
Local File/Directory
    ↓
POST /ingest {"local_path": "/path/to/docs"}
    ↓
process_local_file() or ingest_local_directory()
    ↓
1. Read text content from file
2. Generate SHA-256 hash for deduplication
3. Check Firestore memory_hashes collection
4. If new: semantic_chunk() → 700-token chunks
5. If GCP available: embed() → vectors
6. Store in Firestore:
   - memory_docs: file metadata
   - memory_hashes: deduplication index
   - (future) chunks: searchable content
```

### Google Drive Flow (requires GCP)

```
Google Drive Folder ID
    ↓
POST /ingest {"folder_id": "1abc..."}
    ↓
process_drive_file()
    ↓
1. List files in folder via Drive API
2. Use Drive's md5Checksum for fast dedupe
3. Download file content
4. extract_text() → parse based on mime type
5. semantic_chunk() → 700-token chunks
6. embed() → Vertex AI vectors
7. Store in Matching Engine + Firestore
```

## Current Storage Architecture

### Firestore Collections

**memory_docs** - Document metadata
```json
{
  "file_id": "hash_first_16_chars",
  "file_name": "README.md",
  "file_path": "/home/nmtech/VeriSynthOS/README.md",
  "content_hash": "sha256_full_hash",
  "modified_time": "2025-12-10T12:00:00Z",
  "chunk_count": 15,
  "parent_folder": "/home/nmtech/VeriSynthOS",
  "indexed_at": "2025-12-10T12:05:00Z",
  "source": "local"
}
```

**memory_hashes** - Deduplication index
```json
{
  "file_id": "hash_first_16_chars",
  "file_name": "README.md",
  "indexed_at": "2025-12-10T12:05:00Z"
}
```

**chunks** (planned for search)
```json
{
  "document_id": "doc_ref_id",
  "chunk_index": 0,
  "text": "VeriSynthOS is a commercial platform...",
  "start_char": 0,
  "embedding": [0.123, -0.456, ...],  // optional
  "created_at": "2025-12-10T12:05:00Z"
}
```

## Local vs. GCP Modes

### Local Development Mode (No GCP)
- ✅ File ingestion works
- ✅ Deduplication works (Firestore free tier)
- ✅ Metadata storage works
- ❌ Embeddings disabled (no Vertex AI)
- ❌ Vector search disabled (no Matching Engine)
- 🔄 Full-text search possible (implement with Firestore queries)

### Full GCP Mode
- ✅ Everything in local mode, plus:
- ✅ Vertex AI embeddings (text-embedding-004)
- ✅ Matching Engine vector similarity search
- ✅ Hybrid search (text + semantic)

## Next Steps: Implementing Search

### Option 1: Full-Text Search (No GCP Required)
```python
@app.post("/search")
async def search(req: SearchRequest):
    # Query Firestore chunks collection
    results = db.collection("chunks").where("text", ">=", req.query).limit(req.top_k).get()
    return format_results(results)
```

### Option 2: Vector Search (Requires GCP)
```python
@app.post("/search")
async def search(req: SearchRequest):
    # Embed query
    query_vector = embed([req.query])[0]
    
    # Search Matching Engine
    matches = index.find_neighbors(query_vector, num_neighbors=req.top_k)
    
    # Fetch full text from Firestore
    results = []
    for match in matches:
        doc = db.collection("chunks").document(match.id).get()
        results.append(doc.to_dict())
    
    return {"results": results}
```

### Option 3: Hybrid Search (Best of Both)
```python
@app.post("/search")
async def search(req: SearchRequest):
    # Vector search for semantic similarity
    vector_results = vector_search(req.query, k=req.top_k*2)
    
    # Text search for keyword matches
    text_results = text_search(req.query, k=req.top_k*2)
    
    # Merge and re-rank
    combined = merge_results(vector_results, text_results)
    return {"results": combined[:req.top_k]}
```

## Integration with MAKER Voting

Once search is implemented:

```python
# In orchestrator.agent.py
async def enrich_job_with_memory(job: Dict) -> Dict:
    # Search memory for relevant context
    memory_results = await search_memory(job["query"])
    
    # Add to job context
    job["retrieved_context"] = [r["text"] for r in memory_results]
    
    # Feed to MAKER voting
    verification = verify_claims_maker(job)
    
    return verification
```

## Supported File Types

Currently supported for local ingestion:
- `.txt` - Plain text
- `.md` - Markdown
- `.py` - Python source code
- `.js`, `.ts` - JavaScript/TypeScript
- `.json` - JSON data
- `.yaml`, `.yml` - YAML configuration
- `.html`, `.css` - Web files
- `.rst` - reStructuredText
- `.tex` - LaTeX
- `.csv`, `.tsv` - Tabular data
- `.c`, `.cpp`, `.h`, `.hpp` - C/C++ source
- `.java`, `.go`, `.rs` - Other languages
- `.sh`, `.bash` - Shell scripts

To add more:
1. Add extension to `text_extensions` set in `ingest_local_directory()`
2. For binary formats (PDF, DOCX), add parser in `extract_text()`

## Performance Considerations

### Deduplication
- SHA-256 hashing prevents re-processing identical files
- Check before downloading/reading (fast)

### Chunking
- 700 tokens (~2800 chars) balances context vs. granularity
- 20% overlap preserves context across boundaries
- Adjust in `semantic_chunk()` if needed

### Embeddings
- Batch size: 5 texts per API call (Vertex AI limit)
- Cost: ~$0.00001 per 1000 tokens
- Latency: ~200ms per batch

### Storage
- Firestore: 1GB free, then $0.18/GB/month
- Matching Engine: ~$0.45/hour when deployed
- Consider using Firestore-only for development
