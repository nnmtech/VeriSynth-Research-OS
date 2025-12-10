"""
VeriSynthOS Monitor Agent
Purpose: Logging, QA, alerts, and auditing across the whole agent pipeline.
Provide dashboards and expose health endpoints.
"""

import logging
import hashlib
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from enum import Enum
import json

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import google.auth
from google.cloud import logging as cloud_logging
from google.cloud import firestore
from google.cloud import monitoring_v3
import asyncio

log = logging.getLogger("monitor")
log.setLevel(logging.INFO)

app = FastAPI(title="VeriSynthOS Monitor Agent")

# ------------------------------------------------------------------
# GLOBAL STATE
# ------------------------------------------------------------------
credentials = None
project_id = None
logging_client = None
monitoring_client = None
db = None

# In-memory metrics (for local dev)
metrics_buffer = []
MAX_BUFFER_SIZE = 10000

# ------------------------------------------------------------------
# PYDANTIC MODELS
# ------------------------------------------------------------------
class EventType(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    SUCCESS = "success"

class LogEvent(BaseModel):
    timestamp: str
    agent: str
    event_type: EventType
    message: str
    metadata: Optional[Dict[str, Any]] = None
    job_id: Optional[str] = None
    trace_id: Optional[str] = None

class MetricType(str, Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"

class Metric(BaseModel):
    name: str
    value: float
    type: MetricType
    labels: Optional[Dict[str, str]] = None
    timestamp: Optional[str] = None

class Alert(BaseModel):
    title: str
    severity: str = Field(..., pattern="^(low|medium|high|critical)$")
    message: str
    agent: Optional[str] = None
    job_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class QACheck(BaseModel):
    job_id: str
    check_type: str  # "hallucination", "format", "completeness", "accuracy"
    passed: bool
    score: Optional[float] = None
    issues: List[str] = []
    recommendations: List[str] = []

class MetricsQuery(BaseModel):
    agent: Optional[str] = None
    metric_name: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    aggregation: str = "sum"  # "sum", "avg", "max", "min", "count"

class AuditQuery(BaseModel):
    job_id: Optional[str] = None
    agent: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    event_types: Optional[List[EventType]] = None

# ------------------------------------------------------------------
# STARTUP
# ------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    global credentials, project_id, logging_client, monitoring_client, db
    
    try:
        credentials, project_id = google.auth.default()
        logging_client = cloud_logging.Client(project=project_id, credentials=credentials)
        monitoring_client = monitoring_v3.MetricServiceClient(credentials=credentials)
        db = firestore.Client(project=project_id, credentials=credentials)
        
        # Attach cloud logging handler
        handler = cloud_logging.handlers.CloudLoggingHandler(logging_client)
        cloud_logger = logging.getLogger("cloudLogger")
        cloud_logger.setLevel(logging.INFO)
        cloud_logger.addHandler(handler)
        
        log.info("✅ VeriSynthOS Monitor Agent started")
        log.info(f"✅ Project: {project_id}")
        
        # Start background tasks
        asyncio.create_task(flush_metrics_buffer())
        asyncio.create_task(run_periodic_qa())
        asyncio.create_task(check_agent_health())
        
    except Exception as e:
        log.warning(f"⚠️  GCP not configured: {e}")
        log.info("Running in local dev mode")

# ------------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------------
@app.post("/log_event")
async def log_event(event: LogEvent):
    """
    Log an event from any agent
    """
    # Log to Cloud Logging
    if logging_client:
        logger = logging_client.logger(event.agent)
        
        severity_map = {
            EventType.INFO: "INFO",
            EventType.WARNING: "WARNING",
            EventType.ERROR: "ERROR",
            EventType.CRITICAL: "CRITICAL",
            EventType.SUCCESS: "INFO"
        }
        
        logger.log_struct(
            {
                "message": event.message,
                "metadata": event.metadata,
                "job_id": event.job_id,
                "trace_id": event.trace_id
            },
            severity=severity_map[event.event_type]
        )
    
    # Store in Firestore for audit trail
    if db:
        try:
            db.collection("audit_logs").add({
                **event.model_dump(),
                "indexed_at": datetime.now(timezone.utc).isoformat()
            })
        except Exception as e:
            log.error(f"Failed to write audit log: {e}")
    
    # Check for alert conditions
    if event.event_type in [EventType.ERROR, EventType.CRITICAL]:
        await trigger_alert(Alert(
            title=f"{event.agent} {event.event_type.value}",
            severity="high" if event.event_type == EventType.CRITICAL else "medium",
            message=event.message,
            agent=event.agent,
            job_id=event.job_id,
            metadata=event.metadata
        ))
    
    return {"status": "logged"}

# ------------------------------------------------------------------
# METRICS
# ------------------------------------------------------------------
@app.post("/record_metric")
async def record_metric(metric: Metric):
    """
    Record a metric value
    """
    # Add timestamp if not provided
    if not metric.timestamp:
        metric.timestamp = datetime.now(timezone.utc).isoformat()
    
    # Buffer metrics for batch write
    metrics_buffer.append(metric)
    
    # Write to Cloud Monitoring
    if monitoring_client and project_id:
        try:
            project_name = f"projects/{project_id}"
            
            # Create time series
            series = monitoring_v3.TimeSeries()
            series.metric.type = f"custom.googleapis.com/{metric.name}"
            
            if metric.labels:
                for key, value in metric.labels.items():
                    series.metric.labels[key] = value
            
            series.resource.type = "global"
            series.resource.labels["project_id"] = project_id
            
            # Add data point
            point = monitoring_v3.Point()
            point.value.double_value = metric.value
            
            now = datetime.now(timezone.utc)
            point.interval.end_time.seconds = int(now.timestamp())
            point.interval.end_time.nanos = now.microsecond * 1000
            
            series.points = [point]
            
            # Write asynchronously
            monitoring_client.create_time_series(name=project_name, time_series=[series])
            
        except Exception as e:
            log.error(f"Failed to write metric to Cloud Monitoring: {e}")
    
    return {"status": "recorded"}

async def flush_metrics_buffer():
    """Background task to flush metrics buffer"""
    while True:
        await asyncio.sleep(60)  # Flush every minute
        
        if len(metrics_buffer) > 0:
            log.info(f"Flushing {len(metrics_buffer)} metrics")
            
            # Could batch-write to BigQuery for analytics
            if db:
                try:
                    batch = db.batch()
                    for metric in metrics_buffer[:100]:  # Batch of 100
                        doc_ref = db.collection("metrics").document()
                        batch.set(doc_ref, metric.model_dump())
                    batch.commit()
                except Exception as e:
                    log.error(f"Metrics flush failed: {e}")
            
            metrics_buffer.clear()

# ------------------------------------------------------------------
# QUERYING
# ------------------------------------------------------------------
@app.post("/query_metrics")
async def query_metrics(query: MetricsQuery):
    """
    Query metrics with aggregation
    """
    if not db:
        raise HTTPException(503, "Firestore not available")
    
    # Build Firestore query
    ref = db.collection("metrics")
    
    if query.metric_name:
        ref = ref.where("name", "==", query.metric_name)
    
    if query.start_time:
        ref = ref.where("timestamp", ">=", query.start_time)
    
    if query.end_time:
        ref = ref.where("timestamp", "<=", query.end_time)
    
    results = ref.stream()
    
    # Aggregate
    values = []
    for doc in results:
        data = doc.to_dict()
        
        # Filter by labels if needed
        if query.agent:
            if not data.get("labels", {}).get("agent") == query.agent:
                continue
        
        values.append(data["value"])
    
    # Apply aggregation
    if not values:
        return {"result": 0, "count": 0}
    
    if query.aggregation == "sum":
        result = sum(values)
    elif query.aggregation == "avg":
        result = sum(values) / len(values)
    elif query.aggregation == "max":
        result = max(values)
    elif query.aggregation == "min":
        result = min(values)
    elif query.aggregation == "count":
        result = len(values)
    else:
        result = sum(values)
    
    return {
        "result": result,
        "count": len(values),
        "aggregation": query.aggregation
    }

@app.post("/query_audit")
async def query_audit(query: AuditQuery):
    """
    Query audit trail
    """
    if not db:
        raise HTTPException(503, "Firestore not available")
    
    # Build query
    ref = db.collection("audit_logs")
    
    if query.job_id:
        ref = ref.where("job_id", "==", query.job_id)
    
    if query.agent:
        ref = ref.where("agent", "==", query.agent)
    
    if query.start_time:
        ref = ref.where("timestamp", ">=", query.start_time)
    
    if query.end_time:
        ref = ref.where("timestamp", "<=", query.end_time)
    
    results = ref.limit(1000).stream()
    
    events = []
    for doc in results:
        data = doc.to_dict()
        
        # Filter by event type if specified
        if query.event_types:
            if data.get("event_type") not in [et.value for et in query.event_types]:
                continue
        
        events.append(data)
    
    return {
        "events": events,
        "total": len(events)
    }

# ------------------------------------------------------------------
# ALERTS
# ------------------------------------------------------------------
@app.post("/alert")
async def trigger_alert(alert: Alert):
    """
    Trigger an alert (could send to Slack, email, etc.)
    """
    log.warning(f"🚨 ALERT [{alert.severity}]: {alert.title} - {alert.message}")
    
    # Store alert
    if db:
        try:
            db.collection("alerts").add({
                **alert.model_dump(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "acknowledged": False
            })
        except Exception as e:
            log.error(f"Failed to store alert: {e}")
    
    # TODO: Send to external alerting service (Slack, PagerDuty, etc.)
    # For now, just log
    
    return {"status": "alert_triggered"}

# ------------------------------------------------------------------
# QA CHECKS
# ------------------------------------------------------------------
@app.post("/qa_check")
async def submit_qa_check(check: QACheck):
    """
    Submit QA check results
    """
    if db:
        try:
            db.collection("qa_checks").add({
                **check.model_dump(),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        except Exception as e:
            log.error(f"Failed to store QA check: {e}")
    
    # Alert if QA failed
    if not check.passed:
        await trigger_alert(Alert(
            title=f"QA Check Failed: {check.check_type}",
            severity="medium",
            message=f"Job {check.job_id} failed {check.check_type} check",
            job_id=check.job_id,
            metadata={"issues": check.issues}
        ))
    
    return {"status": "recorded"}

@app.get("/qa_report/{job_id}")
async def get_qa_report(job_id: str):
    """
    Get QA report for a job
    """
    if not db:
        raise HTTPException(503, "Firestore not available")
    
    checks = db.collection("qa_checks").where("job_id", "==", job_id).stream()
    
    report = {
        "job_id": job_id,
        "checks": [],
        "overall_passed": True
    }
    
    for doc in checks:
        data = doc.to_dict()
        report["checks"].append(data)
        if not data.get("passed", False):
            report["overall_passed"] = False
    
    return report

async def run_periodic_qa():
    """Background task to run periodic QA checks"""
    while True:
        await asyncio.sleep(3600)  # Run every hour
        
        log.info("Running periodic QA checks")
        
        # TODO: Implement sampling and automated QA
        # For now, just log
        
        pass

# ------------------------------------------------------------------
# AGENT HEALTH MONITORING
# ------------------------------------------------------------------
async def check_agent_health():
    """Background task to check health of all agents"""
    while True:
        await asyncio.sleep(300)  # Check every 5 minutes
        
        # TODO: Ping all agents and record status
        # For now, just placeholder
        
        pass

# ------------------------------------------------------------------
# DASHBOARD DATA
# ------------------------------------------------------------------
@app.get("/dashboard/summary")
async def dashboard_summary():
    """
    Get summary metrics for dashboard
    """
    if not db:
        return {
            "total_jobs": 0,
            "active_jobs": 0,
            "failed_jobs": 0,
            "error_rate": 0.0,
            "avg_processing_time": 0.0
        }
    
    # Query recent metrics
    one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    
    logs = db.collection("audit_logs").where("timestamp", ">=", one_hour_ago).stream()
    
    total = 0
    errors = 0
    
    for doc in logs:
        data = doc.to_dict()
        total += 1
        if data.get("event_type") in ["error", "critical"]:
            errors += 1
    
    return {
        "total_events_1h": total,
        "error_count_1h": errors,
        "error_rate": (errors / total * 100) if total > 0 else 0.0,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ------------------------------------------------------------------
# UTILITY ENDPOINTS
# ------------------------------------------------------------------
@app.get("/")
async def root():
    return {
        "agent": "monitor",
        "status": "operational",
        "version": "1.0.0",
        "capabilities": ["logging", "metrics", "alerts", "qa", "audit"]
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "cloud_logging": bool(logging_client),
        "cloud_monitoring": bool(monitoring_client),
        "firestore": bool(db)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
