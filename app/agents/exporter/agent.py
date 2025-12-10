"""
Exporter Agent for data export.

Provides export capabilities to various formats.
"""
import json
import time
from typing import Any

import structlog

from app.models.schemas import ExportRequest, ExportResult

logger = structlog.get_logger(__name__)


class ExporterAgent:
    """Exporter Agent for data export."""
    
    def __init__(self) -> None:
        """Initialize Exporter Agent."""
        self.logger = logger.bind(component="exporter_agent")
    
    async def export(self, request: ExportRequest) -> ExportResult:
        """
        Export data to specified format.
        
        Args:
            request: Export request
            
        Returns:
            ExportResult with exported data
        """
        start_time = time.time()
        self.logger.info("starting_export", format=request.format)
        
        # Route to appropriate exporter
        if request.format == "json":
            data, size = await self._export_json(request.data, request.options)
        elif request.format == "csv":
            data, size = await self._export_csv(request.data, request.options)
        elif request.format == "xml":
            data, size = await self._export_xml(request.data, request.options)
        else:
            raise ValueError(f"Unknown export format: {request.format}")
        
        execution_time = time.time() - start_time
        
        self.logger.info(
            "export_complete",
            format=request.format,
            size_bytes=size,
            execution_time=execution_time,
        )
        
        return ExportResult(
            format=request.format,
            data=data,
            size_bytes=size,
            execution_time=execution_time,
        )
    
    async def _export_json(
        self, data: Any, options: dict[str, Any]
    ) -> tuple[str, int]:
        """Export to JSON format."""
        indent = options.get("indent", 2)
        json_str = json.dumps(data, indent=indent)
        return json_str, len(json_str.encode("utf-8"))
    
    async def _export_csv(
        self, data: Any, options: dict[str, Any]
    ) -> tuple[str, int]:
        """Export to CSV format."""
        if not isinstance(data, list):
            data = [data]
        
        if not data:
            return "", 0
        
        # Get headers from first item
        if isinstance(data[0], dict):
            headers = list(data[0].keys())
        else:
            headers = ["value"]
        
        delimiter = options.get("delimiter", ",")
        
        # Build CSV
        lines = [delimiter.join(headers)]
        for item in data:
            if isinstance(item, dict):
                row = [str(item.get(h, "")) for h in headers]
            else:
                row = [str(item)]
            lines.append(delimiter.join(row))
        
        csv_str = "\n".join(lines)
        return csv_str, len(csv_str.encode("utf-8"))
    
    async def _export_xml(
        self, data: Any, options: dict[str, Any]
    ) -> tuple[str, int]:
        """Export to XML format."""
        root_tag = options.get("root_tag", "root")
        item_tag = options.get("item_tag", "item")
        
        def to_xml(obj: Any, tag: str) -> str:
            if isinstance(obj, dict):
                items = "".join(to_xml(v, k) for k, v in obj.items())
                return f"<{tag}>{items}</{tag}>"
            elif isinstance(obj, list):
                items = "".join(to_xml(item, item_tag) for item in obj)
                return f"<{tag}>{items}</{tag}>"
            else:
                return f"<{tag}>{obj}</{tag}>"
        
        xml_str = f'<?xml version="1.0" encoding="UTF-8"?>\n{to_xml(data, root_tag)}'
        return xml_str, len(xml_str.encode("utf-8"))
