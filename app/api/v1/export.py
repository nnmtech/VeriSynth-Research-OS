"""Export agent API endpoints."""
from fastapi import APIRouter, HTTPException

from app.agents.exporter import ExporterAgent
from app.models.schemas import ExportRequest, ExportResult

router = APIRouter()
exporter_agent = ExporterAgent()


@router.post("/", response_model=ExportResult)
async def export_data(request: ExportRequest) -> ExportResult:
    """Export data to specified format."""
    try:
        return await exporter_agent.export(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
