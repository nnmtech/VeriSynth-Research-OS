"""Transform agent API endpoints."""
from fastapi import APIRouter, HTTPException

from app.agents.transformer import TransformerAgent
from app.models.schemas import TransformRequest, TransformResult

router = APIRouter()
transformer_agent = TransformerAgent()


@router.post("/", response_model=TransformResult)
async def transform_data(request: TransformRequest) -> TransformResult:
    """Transform data according to specified type."""
    try:
        return await transformer_agent.transform(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
