"""Tests for transformer agent."""
import pytest

from app.agents.transformer import TransformerAgent
from app.models.schemas import TransformRequest


@pytest.mark.asyncio
async def test_normalize_transform() -> None:
    """Test normalize transformation."""
    agent = TransformerAgent()
    
    request = TransformRequest(
        input_data={"name": "  TEST  ", "value": "DATA"},
        transform_type="normalize",
        parameters={"lowercase": True},
    )
    
    result = await agent.transform(request)
    
    assert result.output_data["name"] == "test"
    assert result.output_data["value"] == "data"


@pytest.mark.asyncio
async def test_aggregate_transform() -> None:
    """Test aggregate transformation."""
    agent = TransformerAgent()
    
    request = TransformRequest(
        input_data=[1, 2, 3, 4, 5],
        transform_type="aggregate",
        parameters={"type": "sum"},
    )
    
    result = await agent.transform(request)
    
    assert result.output_data == 15
