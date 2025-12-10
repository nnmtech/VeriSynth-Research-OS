# orchestrator/agent.py
"""
VeriSynthOS Orchestrator Agent
Purpose: Coordinate workflow between specialist agents. Accepts high-level job requests
and decomposes them into tasks routed to the right agents.
"""

import os
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from enum import Enum

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import google.auth
from google.cloud import firestore
import asyncio
import httpx

from agents.core.maker import first_to_ahead_by_k, strict_json_parser
from agents.core.llm_router import llm_call

log = logging.getLogger("orchestrator")
log.setLevel(logging.INFO)

app = FastAPI(title="VeriSynthOS Orchestrator")

MAKER_MODE = os.getenv("MAKER_MODE", "true").lower() == "true"

# ------------------------------------------------------------------
# GLOBAL STATE
# ------------------------------------------------------------------
credentials = None
project_id = None
db = None

# Agent registry (endpoints)
AGENT_REGISTRY = {
    "memory": os.getenv("MEMORY_AGENT_URL", "http://localhost:7000"),
    "researcher": os.getenv("RESEARCHER_AGENT_URL", "http://localhost:8001"),
    "verifier": os.getenv("VERIFIER_AGENT_URL", "http://localhost:8002"),
    "data_retriever": os.getenv("DATA_RETRIEVER_AGENT_URL", "http://localhost:8003"),
    "transformer": os.getenv("TRANSFORMER_AGENT_URL", "http://localhost:8004"),
    "exporter": os.getenv("EXPORTER_AGENT_URL", "http://localhost:8005"),
    "monitor": os.getenv("MONITOR_AGENT_URL", "http://localhost:8006")
}

# ------------------------------------------------------------------
# PYDANTIC MODELS
# ------------------------------------------------------------------
class JobType(str, Enum):
    RESEARCH_AND_EXPORT = "research-and-export"
    DATA_PIPELINE = "data-pipeline"
    RAG_INGEST = "rag-ingest"
    VERIFICATION = "verification"
    CUSTOM = "custom"

class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

class JobSpec(BaseModel):
    job_id: Optional[str] = None
    type: JobType
    query: Optional[str] = None
    deliverables: List[str] = ["excel"]
    sources: List[str] = ["web"]
    verify: bool = True
    user_prefs: Optional[Dict[str, Any]] = None

class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: float = Field(ge=0.0, le=1.0)
    logs: List[Dict[str, str]]
    result: Optional[Dict[str, Any]] = None

# ------------------------------------------------------------------
# STARTUP
# ------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    global credentials, project_id, db
    
    try:
        credentials, project_id = google.auth.default()
        db = firestore.Client(project=project_id, credentials=credentials)
        
        log.info("✅ VeriSynthOS Orchestrator started")
        log.info(f"✅ Project: {project_id}")
        log.info(f"✅ MAKER mode: {MAKER_MODE}")
        
        # Start background job processor
        asyncio.create_task(process_job_queue())
        
    except Exception as e:
        log.warning(f"⚠️  GCP not configured: {e}")

# ------------------------------------------------------------------
# JOB MANAGEMENT
# ------------------------------------------------------------------
@app.post("/start_job")
async def start_job(spec: JobSpec, background_tasks: BackgroundTasks) -> Dict:
    """
    Start a new job
    """
    # Generate job ID
    job_id = spec.job_id or f"job-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
    
    # Create job document
    job_doc = {
        "job_id": job_id,
        "spec": spec.model_dump(),
        "status": JobStatus.QUEUED.value,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "progress": 0.0,
        "logs": [],
        "subtasks": []
    }
    
    if db:
        db.collection("jobs").document(job_id).set(job_doc)
    
    # Start processing in background
    background_tasks.add_task(execute_job, job_id, spec)
    
    log.info(f"✅ Job {job_id} created")
    
    return {"job_id": job_id, "status": "queued"}

@app.get("/job_status/{job_id}")
async def get_job_status(job_id: str) -> JobStatusResponse:
    """
    Get job status
    """
    if not db:
        raise HTTPException(503, "Firestore not available")
    
    doc = db.collection("jobs").document(job_id).get()
    
    if not doc.exists:
        raise HTTPException(404, "Job not found")
    
    data = doc.to_dict()
    
    return JobStatusResponse(
        job_id=job_id,
        status=JobStatus(data["status"]),
        progress=data.get("progress", 0.0),
        logs=data.get("logs", []),
        result=data.get("result")
    )

@app.post("/cancel_job/{job_id}")
async def cancel_job(job_id: str):
    """
    Cancel a running job
    """
    if not db:
        raise HTTPException(503, "Firestore not available")
    
    db.collection("jobs").document(job_id).update({
        "status": JobStatus.CANCELLED.value,
        "cancelled_at": datetime.now(timezone.utc).isoformat()
    })
    
    log.info(f"Job {job_id} cancelled")
    
    return {"status": "cancelled"}

# ------------------------------------------------------------------
# JOB EXECUTION
# ------------------------------------------------------------------
async def execute_job(job_id: str, spec: JobSpec):
    """
    Execute a job by decomposing into subtasks and routing to agents
    """
    log.info(f"Executing job {job_id}: {spec.type}")
    
    try:
        # Update status
        update_job_status(job_id, JobStatus.RUNNING, 0.1, "Starting job execution")
        
        # Decompose based on job type
        if spec.type == JobType.RESEARCH_AND_EXPORT:
            result = await execute_research_and_export(job_id, spec)
        elif spec.type == JobType.DATA_PIPELINE:
            result = await execute_data_pipeline(job_id, spec)
        elif spec.type == JobType.RAG_INGEST:
            result = await execute_rag_ingest(job_id, spec)
        elif spec.type == JobType.VERIFICATION:
            result = await execute_verification(job_id, spec)
        else:
            raise ValueError(f"Unsupported job type: {spec.type}")
        
        # Mark as succeeded
        update_job_status(job_id, JobStatus.SUCCEEDED, 1.0, "Job completed successfully", result)
        
        log.info(f"✅ Job {job_id} completed")
        
    except Exception as e:
        log.error(f"❌ Job {job_id} failed: {e}")
        update_job_status(job_id, JobStatus.FAILED, 0.0, f"Job failed: {str(e)}")

# ------------------------------------------------------------------
# JOB WORKFLOWS
# ------------------------------------------------------------------
async def execute_research_and_export(job_id: str, spec: JobSpec) -> Dict:
    """
    Research → RAG → Verify → Export workflow
    """
    result = {}
    
    # Step 1: Research
    update_job_status(job_id, JobStatus.RUNNING, 0.2, "Researching sources")
    research_result = await call_agent("researcher", "/research", {
        "query": spec.query,
        "max_results": 30,
        "source_types": spec.sources
    })
    result["research"] = research_result
    
    # Step 2: Ingest to RAG
    update_job_status(job_id, JobStatus.RUNNING, 0.4, "Ingesting to memory")
    # TODO: Ingest research results to memory agent
    
    # Step 3: Verify key claims
    if spec.verify:
        update_job_status(job_id, JobStatus.RUNNING, 0.6, "Verifying claims")
        # Extract claims from research synthesis
        claims = []  # TODO: Extract from research_result
        verify_result = await call_agent("verifier", "/verify_claims", {"claims": claims})
        result["verification"] = verify_result
    
    # Step 4: Export
    update_job_status(job_id, JobStatus.RUNNING, 0.8, "Generating deliverables")
    export_result = await call_agent("exporter", "/export", {
        "format": spec.deliverables,
        "data": result
    })
    result["exports"] = export_result
    
    return result

async def execute_data_pipeline(job_id: str, spec: JobSpec) -> Dict:
    """
    Retrieve → Transform → Export workflow
    """
    result = {}
    
    # Step 1: Retrieve data
    update_job_status(job_id, JobStatus.RUNNING, 0.3, "Retrieving data")
    data_result = await call_agent("data_retriever", "/fetch_data", spec.user_prefs)
    result["data"] = data_result
    
    # Step 2: Transform
    update_job_status(job_id, JobStatus.RUNNING, 0.6, "Transforming data")
    transform_result = await call_agent("transformer", "/transform", {
        "data_path": data_result.get("data_path"),
        "spec": spec.user_prefs.get("transform_spec", {})
    })
    result["transform"] = transform_result
    
    # Step 3: Export
    update_job_status(job_id, JobStatus.RUNNING, 0.9, "Exporting")
    export_result = await call_agent("exporter", "/export", {
        "format": spec.deliverables,
        "data_path": transform_result.get("output_path")
    })
    result["exports"] = export_result
    
    return result

async def execute_rag_ingest(job_id: str, spec: JobSpec) -> Dict:
    """
    Ingest documents to memory agent
    """
    update_job_status(job_id, JobStatus.RUNNING, 0.5, "Ingesting documents")
    
    ingest_result = await call_agent("memory", "/ingest", spec.user_prefs)
    
    return {"ingested": ingest_result}

async def execute_verification(job_id: str, spec: JobSpec) -> Dict:
    """
    Verify claims workflow
    """
    update_job_status(job_id, JobStatus.RUNNING, 0.5, "Verifying claims")
    
    verify_result = await call_agent("verifier", "/verify_claims", {
        "claims": spec.user_prefs.get("claims", [])
    })
    
    return {"verification": verify_result}

# ------------------------------------------------------------------
# AGENT CALLING
# ------------------------------------------------------------------
async def call_agent(agent_name: str, endpoint: str, payload: Dict) -> Dict:
    """
    Call another agent via HTTP
    """
    url = AGENT_REGISTRY.get(agent_name)
    if not url:
        raise ValueError(f"Agent not found in registry: {agent_name}")
    
    full_url = f"{url}{endpoint}"
    
    log.info(f"Calling {agent_name}: {endpoint}")
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(full_url, json=payload)
        response.raise_for_status()
        return response.json()

# ------------------------------------------------------------------
# UTILITIES
# ------------------------------------------------------------------
def update_job_status(job_id: str, status: JobStatus, progress: float, message: str, result: Dict = None):
    """
    Update job status in Firestore
    """
    if not db:
        return
    
    update_data = {
        "status": status.value,
        "progress": progress,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Append log
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": message
    }
    
    db.collection("jobs").document(job_id).update({
        **update_data,
        "logs": firestore.ArrayUnion([log_entry])
    })
    
    if result:
        db.collection("jobs").document(job_id).update({"result": result})

async def process_job_queue():
    """
    Background task to process queued jobs
    """
    while True:
        await asyncio.sleep(5)
        
        if not db:
            continue
        
        # Find queued jobs
        queued = db.collection("jobs").where("status", "==", JobStatus.QUEUED.value).limit(10).stream()
        
        for doc in queued:
            data = doc.to_dict()
            spec = JobSpec(**data["spec"])
            
            # Execute job
            asyncio.create_task(execute_job(data["job_id"], spec))

# ------------------------------------------------------------------
# MEMORY CONTEXT INJECTION (Legacy support)
# ------------------------------------------------------------------
def enrich_job_with_memory(job):
    """Legacy function for memory context injection"""
    if not (hasattr(job, 'user_memory_folders') and hasattr(job, 'org_canonical_folders')):
        return
    if not (job.user_memory_folders or job.org_canonical_folders):
        return
    
    passages = []  # Placeholder until search endpoint is implemented
    
    job.preliminary_context = passages
    
    if any(p.get("score", 0) > 0.88 for p in passages[:10]):
        job.short_circuit_hint = "High-confidence memory match — prefer cached sources"

# ------------------------------------------------------------------
# ENDPOINTS
# ------------------------------------------------------------------
@app.get("/")
async def root():
    return {
        "agent": "orchestrator",
        "status": "operational",
        "version": "1.0.0",
        "maker_mode": MAKER_MODE,
        "registered_agents": list(AGENT_REGISTRY.keys())
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "firestore": bool(db),
        "agents": AGENT_REGISTRY
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
