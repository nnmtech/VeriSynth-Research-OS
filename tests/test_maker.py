"""Tests for MAKER core."""
import pytest

from app.core.maker import MAKER, AgentStatus, MAKERConfig


@pytest.mark.asyncio
async def test_maker_first_to_ahead_by_k() -> None:
    """Test MAKER first_to_ahead_by_k strategy."""
    maker = MAKER(config=MAKERConfig(k_value=2, timeout_seconds=10))
    
    # Create sample agents
    async def agent(**kwargs):  # type: ignore
        return {"result": "success", "confidence": 0.8}
    
    agents = [agent for _ in range(5)]
    agent_inputs = [{"data": "test"} for _ in range(5)]
    
    result = await maker.first_to_ahead_by_k(agents, agent_inputs, k=2)
    
    assert result is not None
    assert result.status in [AgentStatus.COMPLETED, AgentStatus.RED_FLAGGED]
    assert result.confidence > 0
