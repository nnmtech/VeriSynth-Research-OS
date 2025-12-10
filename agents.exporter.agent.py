# agents/exporter/agent.py
"""
VeriSynthOS Exporter Agent - REST API
Purpose: Generate Excel, PDF, DOCX deliverables with MAKER voting
"""

import logging
from agents.core.maker import first_to_ahead_by_k, strict_json_parser
from agents.core.llm_router import llm_call
from pydantic import BaseModel
from typing import Any

from fastapi import FastAPI, HTTPException

log = logging.getLogger("exporter")
log.setLevel(logging.INFO)

app = FastAPI(title="VeriSynthOS Exporter Agent")

class ExportManifest(BaseModel):
    # Your actual export schema — whatever you use for Excel/PDF structure
    format: str
    sections: list[dict]
    charts: list[dict]
    provenance: dict

class ExportRequest(BaseModel):
    format: list[str]
    data: dict
    data_path: str = None

def build_export_prompt(task_input: dict) -> str:
    """Build the export prompt from task input."""
    return f"Generate export manifest for: {task_input}"

def render_and_upload(manifest: ExportManifest) -> Any:
    """Render the manifest and upload to storage."""
    import pandas as pd
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from datetime import datetime
    import google.auth
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    import tempfile
    import os
    
    log.info(f"Rendering export in format: {manifest.format}")
    
    try:
        # Load data from provenance
        data_path = manifest.provenance.get("data_path")
        if not data_path:
            raise ValueError("No data_path in export manifest")
        
        # Load DataFrame
        if data_path.endswith(".csv"):
            df = pd.read_csv(data_path)
        elif data_path.endswith(".parquet"):
            df = pd.read_parquet(data_path)
        else:
            raise ValueError(f"Unsupported format: {data_path}")
        
        log.info(f"Loaded {len(df)} rows for export")
        
        output_files = []
        
        # Excel export
        if manifest.format in ["excel", "xlsx"]:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                output_path = tmp.name
            
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                # Write main data
                df.to_excel(writer, sheet_name='Data', index=False)
                
                # Write provenance sheet
                provenance_df = pd.DataFrame([manifest.provenance])
                provenance_df.to_excel(writer, sheet_name='Provenance', index=False)
                
                # Apply formatting
                workbook = writer.book
                worksheet = workbook['Data']
                
                # Header formatting
                header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
                header_font = Font(bold=True, color="FFFFFF")
                
                for cell in worksheet[1]:
                    cell.fill = header_fill
                    cell.font = header_font
            
            output_files.append({"path": output_path, "format": "xlsx"})
            log.info(f"✅ Excel file created: {output_path}")
        
        # CSV export
        elif manifest.format == "csv":
            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode='w') as tmp:
                output_path = tmp.name
            
            df.to_csv(output_path, index=False)
            output_files.append({"path": output_path, "format": "csv"})
            log.info(f"✅ CSV file created: {output_path}")
        
        # PDF export (basic)
        elif manifest.format == "pdf":
            # For PDF, we'd use ReportLab or weasyprint
            # Simplified version here
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                output_path = tmp.name
            
            # TODO: Implement proper PDF rendering with ReportLab
            # For now, convert DataFrame to HTML then PDF
            html = df.head(100).to_html(index=False)
            
            try:
                import pdfkit
                pdfkit.from_string(html, output_path)
                output_files.append({"path": output_path, "format": "pdf"})
                log.info(f"✅ PDF file created: {output_path}")
            except:
                log.warning("PDF generation requires wkhtmltopdf - skipping")
        
        # Upload to Google Drive
        credentials, project_id = google.auth.default()
        drive_service = build('drive', 'v3', credentials=credentials, cache_discovery=False)
        
        drive_links = []
        
        for file_info in output_files:
            file_metadata = {
                'name': f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{file_info['format']}",
                'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if file_info['format'] == 'xlsx' else f'text/{file_info["format"]}'
            }
            
            media = MediaFileUpload(file_info['path'], resumable=True)
            
            file = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()
            
            drive_links.append({
                "file_id": file.get('id'),
                "link": file.get('webViewLink'),
                "format": file_info['format']
            })
            
            log.info(f"✅ Uploaded to Drive: {file.get('webViewLink')}")
            
            # Clean up temp file
            os.unlink(file_info['path'])
        
        return {
            "status": "success",
            "manifest": manifest.model_dump(),
            "files": drive_links
        }
        
    except Exception as e:
        log.error(f"Export rendering failed: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "manifest": manifest.model_dump()
        }

def export_maker(request: dict) -> Any:
    def sampler(task_input: dict) -> str:
        prompt = build_export_prompt(task_input)
        return llm_call(
            prompt=prompt,
            system_prompt="You are a precise document formatter. Return ONLY valid JSON matching the ExportManifest schema. No explanations.",
            temperature=0.0,  # ← Critical: deterministic formatting
            max_tokens=1400   # ← Export prompts are longer than verification
        )

    final = first_to_ahead_by_k(
        task_input=request,
        sampler=sampler,
        parser=lambda raw: strict_json_parser(raw, ExportManifest),
        k=3,
        max_tokens=None,  # ← Use dynamic threshold from maker.py (750 or 1200)
    )
    return render_and_upload(final)

# REST API Endpoints
@app.post("/export")
async def export(req: ExportRequest):
    """
    Export data with MAKER voting
    """
    log.info(f"Exporting to formats: {req.format}")
    
    try:
        result = export_maker(req.model_dump())
        
        log.info(f"✅ Export complete")
        
        return result
    
    except Exception as e:
        log.error(f"Export failed: {e}")
        raise HTTPException(500, f"Export error: {str(e)}")

@app.get("/")
async def root():
    return {
        "agent": "exporter",
        "status": "operational",
        "version": "1.0.0",
        "maker_mode": True,
        "maker_k": 3
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
