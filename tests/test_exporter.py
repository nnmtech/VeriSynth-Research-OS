"""Tests for exporter agent."""
import json

import pytest

from app.agents.exporter import ExporterAgent
from app.models.schemas import ExportRequest


@pytest.mark.asyncio
async def test_json_export() -> None:
    """Test JSON export."""
    agent = ExporterAgent()
    
    data = {"name": "test", "value": 123}
    request = ExportRequest(
        data=data,
        format="json",
        options={"indent": 2},
    )
    
    result = await agent.export(request)
    
    assert result.format == "json"
    assert result.data is not None
    
    # Verify it's valid JSON
    parsed = json.loads(result.data)
    assert parsed == data


@pytest.mark.asyncio
async def test_csv_export() -> None:
    """Test CSV export."""
    agent = ExporterAgent()
    
    data = [
        {"name": "Alice", "age": 30},
        {"name": "Bob", "age": 25},
    ]
    request = ExportRequest(
        data=data,
        format="csv",
        options={},
    )
    
    result = await agent.export(request)
    
    assert result.format == "csv"
    assert result.data is not None
    assert "name,age" in result.data
    assert "Alice,30" in result.data
