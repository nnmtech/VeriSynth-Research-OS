"""Pydantic models for VeriSynth Research OS."""
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentType(str, Enum):
    """Types of agents in the system."""
    MEMORY = "memory"
    VERIFIER = "verifier"
    TRANSFORMER = "transformer"
    EXPORTER = "exporter"


class TaskStatus(str, Enum):
    """Status of a task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# Base schemas
class BaseSchema(BaseModel):
    """Base schema with common fields."""

    class Config:
        """Pydantic config."""
        from_attributes = True


# Request/Response models
class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    timestamp: datetime
    environment: str


class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    detail: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# Memory models
class MemoryQuery(BaseModel):
    """Memory search query."""
    query: str = Field(..., description="Search query text")
    max_results: int = Field(default=10, ge=1, le=100)
    similarity_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    filters: dict[str, Any] = Field(default_factory=dict)


class MemoryEntry(BaseModel):
    """Memory entry with provenance."""
    id: str
    content: str
    embedding: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MemorySearchResult(BaseModel):
    """Memory search result."""
    entries: list[MemoryEntry]
    total: int
    query: str
    execution_time: float


# Verification models
class VerificationRequest(BaseModel):
    """Request for verification."""
    content: str = Field(..., description="Content to verify")
    context: dict[str, Any] = Field(default_factory=dict)
    verification_type: str = Field(default="standard")


class VerificationVote(BaseModel):
    """Single verification vote."""
    verifier_id: str
    vote: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class VerificationResult(BaseModel):
    """Verification result with voting."""
    verified: bool
    confidence: float
    votes: list[VerificationVote]
    consensus: dict[str, Any]
    execution_time: float


# Transform models
class TransformRequest(BaseModel):
    """Request for transformation."""
    input_data: Any = Field(..., description="Data to transform")
    transform_type: str = Field(..., description="Type of transformation")
    parameters: dict[str, Any] = Field(default_factory=dict)


class TransformResult(BaseModel):
    """Transformation result."""
    output_data: Any
    transform_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    execution_time: float


# Export models
class ExportRequest(BaseModel):
    """Request for export."""
    data: Any = Field(..., description="Data to export")
    format: str = Field(..., description="Export format (json, csv, xml, etc.)")
    options: dict[str, Any] = Field(default_factory=dict)


class ExportResult(BaseModel):
    """Export result."""
    format: str
    url: str | None = None
    data: str | None = None
    size_bytes: int
    execution_time: float


# LLM models
class LLMRequest(BaseModel):
    """LLM completion request."""
    messages: list[dict[str, str]] = Field(..., description="List of messages")
    provider: str | None = Field(None, description="LLM provider")
    model: str | None = Field(None, description="Model name")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1000, ge=1, le=32000)


class LLMResponse(BaseModel):
    """LLM completion response."""
    content: str
    model: str
    provider: str
    usage: dict[str, int]


# MAKER models
class MAKERRequest(BaseModel):
    """MAKER execution request."""
    task_type: str = Field(..., description="Type of task to execute")
    inputs: dict[str, Any] = Field(..., description="Task inputs")
    k_value: int | None = Field(None, ge=1, le=10)
    timeout_seconds: int | None = Field(None, ge=1, le=600)


class MAKERAgentResult(BaseModel):
    """MAKER agent result."""
    agent_id: str
    status: str
    confidence: float
    execution_time: float
    red_flags: list[str]


class MAKERResult(BaseModel):
    """MAKER execution result."""
    winner: MAKERAgentResult
    total_agents: int
    execution_time: float
    metadata: dict[str, Any] = Field(default_factory=dict)


# Task models
class TaskCreate(BaseModel):
    """Task creation request."""
    task_type: str = Field(..., description="Type of task")
    inputs: dict[str, Any] = Field(..., description="Task inputs")
    priority: int = Field(default=5, ge=1, le=10)


class Task(BaseModel):
    """Task model."""
    id: str
    task_type: str
    status: TaskStatus
    inputs: dict[str, Any]
    outputs: dict[str, Any] | None = None
    priority: int
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
