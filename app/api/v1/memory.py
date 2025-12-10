"""Memory agent API endpoints."""
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from app.agents.memory import MemoryAgent
from app.models.schemas import MemoryEntry, MemoryQuery, MemorySearchResult

router = APIRouter()
memory_agent = MemoryAgent()


@router.post("/store", response_model=MemoryEntry)
async def store_memory(
    content: str,
    metadata: Optional[dict[str, Any]] = None,
    provenance: Optional[dict[str, Any]] = None,
) -> MemoryEntry:
    """Store content in memory with provenance."""
    try:
        return await memory_agent.store(
            content=content,
            metadata=metadata,
            provenance=provenance,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search", response_model=MemorySearchResult)
async def search_memory(query: MemoryQuery) -> MemorySearchResult:
    """Search memory with semantic similarity."""
    try:
        return await memory_agent.search(query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{entry_id}", response_model=MemoryEntry)
async def get_memory(entry_id: str) -> MemoryEntry:
    """Get memory entry by ID."""
    entry = await memory_agent.get_by_id(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return entry


@router.put("/{entry_id}/provenance")
async def update_provenance(
    entry_id: str,
    provenance_update: dict[str, Any],
) -> dict[str, str]:
    """Update provenance information."""
    success = await memory_agent.update_provenance(entry_id, provenance_update)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update provenance")
    return {"status": "success", "entry_id": entry_id}
