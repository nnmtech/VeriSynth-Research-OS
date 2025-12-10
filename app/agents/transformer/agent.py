"""
Transformer Agent for data transformations.

Provides various data transformation capabilities.
"""
import time
from typing import Any

import structlog

from app.models.schemas import TransformRequest, TransformResult

logger = structlog.get_logger(__name__)


class TransformerAgent:
    """Transformer Agent for data transformations."""

    def __init__(self) -> None:
        """Initialize Transformer Agent."""
        self.logger = logger.bind(component="transformer_agent")

    async def transform(self, request: TransformRequest) -> TransformResult:
        """
        Transform data according to specified type.

        Args:
            request: Transform request

        Returns:
            TransformResult with transformed data
        """
        start_time = time.time()
        self.logger.info("starting_transform", transform_type=request.transform_type)

        # Route to appropriate transformer
        if request.transform_type == "normalize":
            output = await self._normalize(request.input_data, request.parameters)
        elif request.transform_type == "aggregate":
            output = await self._aggregate(request.input_data, request.parameters)
        elif request.transform_type == "filter":
            output = await self._filter(request.input_data, request.parameters)
        elif request.transform_type == "map":
            output = await self._map(request.input_data, request.parameters)
        else:
            raise ValueError(f"Unknown transform type: {request.transform_type}")

        execution_time = time.time() - start_time

        self.logger.info(
            "transform_complete",
            transform_type=request.transform_type,
            execution_time=execution_time,
        )

        return TransformResult(
            output_data=output,
            transform_type=request.transform_type,
            metadata={"parameters": request.parameters},
            execution_time=execution_time,
        )

    async def _normalize(self, data: Any, parameters: dict[str, Any]) -> Any:
        """Normalize data."""
        if isinstance(data, dict):
            return {k: self._normalize_value(v, parameters) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._normalize_value(item, parameters) for item in data]
        return data

    def _normalize_value(self, value: Any, parameters: dict[str, Any]) -> Any:
        """Normalize a single value."""
        if isinstance(value, str):
            return value.strip().lower() if parameters.get("lowercase") else value.strip()
        return value

    async def _aggregate(self, data: Any, parameters: dict[str, Any]) -> Any:
        """Aggregate data."""
        if not isinstance(data, list):
            return data

        agg_type = parameters.get("type", "count")

        if agg_type == "count":
            return len(data)
        elif agg_type == "sum":
            return sum(item if isinstance(item, (int, float)) else 0 for item in data)
        elif agg_type == "average":
            numeric_items = [item for item in data if isinstance(item, (int, float))]
            return sum(numeric_items) / len(numeric_items) if numeric_items else 0

        return data

    async def _filter(self, data: Any, parameters: dict[str, Any]) -> Any:
        """Filter data."""
        if not isinstance(data, list):
            return data

        filter_key = parameters.get("key")
        filter_value = parameters.get("value")

        if filter_key and filter_value is not None:
            return [
                item
                for item in data
                if isinstance(item, dict) and item.get(filter_key) == filter_value
            ]

        return data

    async def _map(self, data: Any, parameters: dict[str, Any]) -> Any:
        """Map data to new structure."""
        if not isinstance(data, list):
            return data

        mapping = parameters.get("mapping", {})

        if not mapping:
            return data

        return [
            {new_key: item.get(old_key) for old_key, new_key in mapping.items()}
            for item in data
            if isinstance(item, dict)
        ]
