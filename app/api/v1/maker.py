"""MAKER API endpoints."""
from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.maker import MAKER, MAKERConfig
from app.models.schemas import MAKERAgentResult, MAKERRequest, MAKERResult

router = APIRouter()


@router.post("/execute", response_model=MAKERResult)
async def execute_maker(request: MAKERRequest) -> MAKERResult:
    """Execute MAKER with first_to_ahead_by_k strategy."""
    try:
        # Create MAKER config
        config = MAKERConfig(
            k_value=request.k_value or 2,
            timeout_seconds=request.timeout_seconds or 300,
        )

        maker = MAKER(config=config)

        # Create sample agents for demonstration
        # In production, these would be dynamically generated based on task_type
        async def sample_agent(**kwargs: Any) -> dict[str, Any]:
            """Sample agent that returns a result."""
            return {
                "result": f"Processed task: {request.task_type}",
                "reasoning": "Sample reasoning",
                "confidence": 0.85,
            }

        # Execute MAKER
        agents = [sample_agent for _ in range(5)]
        agent_inputs = [request.inputs for _ in range(5)]

        result = await maker.first_to_ahead_by_k(
            agents=agents,
            agent_inputs=agent_inputs,
            k=config.k_value,
        )

        # Convert to response
        winner = MAKERAgentResult(
            agent_id=result.agent_id,
            status=result.status.value,
            confidence=result.confidence,
            execution_time=result.execution_time,
            red_flags=result.red_flags,
        )

        return MAKERResult(
            winner=winner,
            total_agents=len(agents),
            execution_time=result.execution_time,
            metadata=result.metadata,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
