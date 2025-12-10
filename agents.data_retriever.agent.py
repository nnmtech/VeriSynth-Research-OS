"""
VeriSynthOS Data Retriever Agent
Purpose: Fetch and assemble structured data from APIs, databases, and public datasets.
Normalize into tabular formats for downstream processing.
"""

import logging
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Union
from enum import Enum
import json
import io

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import google.auth
from google.cloud import bigquery
from google.cloud import storage
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import requests
import pandas as pd

log = logging.getLogger("data_retriever")
log.setLevel(logging.INFO)

app = FastAPI(title="VeriSynthOS Data Retriever Agent")

# ------------------------------------------------------------------
# GLOBAL STATE
# ------------------------------------------------------------------
credentials = None
project_id = None
bq_client = None
storage_client = None
sheets_service = None
drive_service = None

# Rate limiting
MAX_BQ_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB query limit

# ------------------------------------------------------------------
# PYDANTIC MODELS
# ------------------------------------------------------------------
class SourceType(str, Enum):
    BIGQUERY = "bigquery"
    SHEETS = "sheets"
    REST_API = "rest"
    GCS_CSV = "gcs_csv"
    URL_CSV = "url_csv"
    URL_JSON = "url_json"

class BigQuerySpec(BaseModel):
    query: str
    params: Optional[Dict[str, Any]] = None
    max_bytes: Optional[int] = Field(default=MAX_BQ_BYTES)

class SheetsSpec(BaseModel):
    spreadsheet_id: str
    range: str = "A1:ZZ"  # Default to all data

class RestApiSpec(BaseModel):
    url: str
    method: str = "GET"
    headers: Optional[Dict[str, str]] = None
    params: Optional[Dict[str, Any]] = None
    body: Optional[Dict[str, Any]] = None
    auth_type: Optional[str] = None  # "bearer", "apikey", "oauth2"
    credentials: Optional[Dict[str, str]] = None

class DataRequest(BaseModel):
    source: SourceType
    spec: Union[BigQuerySpec, SheetsSpec, RestApiSpec, Dict[str, Any]]
    output_format: str = Field(default="json", pattern="^(json|csv|dataframe)$")

class ColumnSchema(BaseModel):
    name: str
    type: str
    nullable: bool = True

class DataResponse(BaseModel):
    table_name: str
    rows: int
    columns: List[ColumnSchema]
    preview: List[Dict[str, Any]] = Field(default=[], max_length=10)
    data_path: Optional[str] = None  # GCS path if too large
    provenance: Dict[str, Any]
    warnings: List[str] = []

# ------------------------------------------------------------------
# STARTUP
# ------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    global credentials, project_id, bq_client, storage_client, sheets_service, drive_service
    
    try:
        credentials, project_id = google.auth.default()
        bq_client = bigquery.Client(project=project_id, credentials=credentials)
        storage_client = storage.Client(project=project_id, credentials=credentials)
        sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        
        log.info("✅ VeriSynthOS Data Retriever Agent started")
        log.info(f"✅ Project: {project_id}")
        
    except Exception as e:
        log.warning(f"⚠️  GCP not configured: {e}")
        log.info("Running in local dev mode")

# ------------------------------------------------------------------
# BIGQUERY RETRIEVAL
# ------------------------------------------------------------------
def fetch_bigquery(spec: BigQuerySpec) -> pd.DataFrame:
    """
    Execute BigQuery query with cost guards and parameter support
    """
    if not bq_client:
        raise HTTPException(503, "BigQuery client not available")
    
    log.info(f"Executing BigQuery query (max {spec.max_bytes} bytes)")
    
    try:
        # Configure query with dry-run to check cost
        job_config = bigquery.QueryJobConfig(
            maximum_bytes_billed=spec.max_bytes,
            query_parameters=[]
        )
        
        # Add parameters if provided
        if spec.params:
            for key, value in spec.params.items():
                if isinstance(value, int):
                    job_config.query_parameters.append(
                        bigquery.ScalarQueryParameter(key, "INT64", value)
                    )
                elif isinstance(value, str):
                    job_config.query_parameters.append(
                        bigquery.ScalarQueryParameter(key, "STRING", value)
                    )
                # Add more types as needed
        
        # Dry run to estimate cost
        job_config_dry = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        dry_run_job = bq_client.query(spec.query, job_config=job_config_dry)
        
        bytes_processed = dry_run_job.total_bytes_processed
        log.info(f"Query will process {bytes_processed:,} bytes")
        
        if bytes_processed > spec.max_bytes:
            raise HTTPException(
                400, 
                f"Query would process {bytes_processed:,} bytes, exceeding limit of {spec.max_bytes:,}"
            )
        
        # Execute actual query
        query_job = bq_client.query(spec.query, job_config=job_config)
        df = query_job.to_dataframe()
        
        log.info(f"✅ Retrieved {len(df)} rows from BigQuery")
        return df
        
    except Exception as e:
        log.error(f"BigQuery fetch failed: {e}")
        raise HTTPException(500, f"BigQuery error: {str(e)}")

# ------------------------------------------------------------------
# GOOGLE SHEETS RETRIEVAL
# ------------------------------------------------------------------
def fetch_sheets(spec: SheetsSpec) -> pd.DataFrame:
    """
    Fetch data from Google Sheets
    """
    if not sheets_service:
        raise HTTPException(503, "Sheets API not available")
    
    log.info(f"Fetching from Google Sheets: {spec.spreadsheet_id}")
    
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spec.spreadsheet_id,
            range=spec.range
        ).execute()
        
        values = result.get('values', [])
        
        if not values:
            raise HTTPException(404, "No data found in specified range")
        
        # First row as headers
        headers = values[0]
        data = values[1:]
        
        df = pd.DataFrame(data, columns=headers)
        
        log.info(f"✅ Retrieved {len(df)} rows from Sheets")
        return df
        
    except HttpError as e:
        log.error(f"Sheets fetch failed: {e}")
        raise HTTPException(500, f"Sheets API error: {str(e)}")

# ------------------------------------------------------------------
# REST API RETRIEVAL
# ------------------------------------------------------------------
def fetch_rest_api(spec: RestApiSpec) -> pd.DataFrame:
    """
    Fetch data from REST API with authentication support
    """
    log.info(f"Fetching from REST API: {spec.url}")
    
    headers = spec.headers or {}
    
    # Handle authentication
    if spec.auth_type == "bearer" and spec.credentials:
        headers["Authorization"] = f"Bearer {spec.credentials.get('token')}"
    elif spec.auth_type == "apikey" and spec.credentials:
        # API key can be in header or param
        if spec.credentials.get("header"):
            headers[spec.credentials["header"]] = spec.credentials["key"]
        else:
            spec.params = spec.params or {}
            spec.params["api_key"] = spec.credentials["key"]
    
    try:
        # Make request
        if spec.method.upper() == "GET":
            response = requests.get(
                spec.url,
                headers=headers,
                params=spec.params,
                timeout=60
            )
        elif spec.method.upper() == "POST":
            response = requests.post(
                spec.url,
                headers=headers,
                params=spec.params,
                json=spec.body,
                timeout=60
            )
        else:
            raise HTTPException(400, f"Unsupported HTTP method: {spec.method}")
        
        response.raise_for_status()
        
        # Parse response
        data = response.json()
        
        # Convert to DataFrame
        if isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict):
            # Handle nested data structures
            if "data" in data:
                df = pd.DataFrame(data["data"])
            elif "results" in data:
                df = pd.DataFrame(data["results"])
            else:
                # Flatten single-level dict
                df = pd.DataFrame([data])
        else:
            raise HTTPException(500, "Unexpected API response format")
        
        log.info(f"✅ Retrieved {len(df)} rows from REST API")
        return df
        
    except requests.exceptions.RequestException as e:
        log.error(f"REST API fetch failed: {e}")
        raise HTTPException(500, f"REST API error: {str(e)}")

# ------------------------------------------------------------------
# CSV/JSON FILE RETRIEVAL
# ------------------------------------------------------------------
def fetch_csv_gcs(uri: str) -> pd.DataFrame:
    """Fetch CSV from GCS bucket"""
    if not storage_client:
        raise HTTPException(503, "GCS client not available")
    
    log.info(f"Fetching CSV from GCS: {uri}")
    
    try:
        # Parse gs://bucket/path
        parts = uri.replace("gs://", "").split("/", 1)
        bucket_name = parts[0]
        blob_name = parts[1]
        
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        
        content = blob.download_as_text()
        df = pd.read_csv(io.StringIO(content))
        
        log.info(f"✅ Retrieved {len(df)} rows from GCS CSV")
        return df
        
    except Exception as e:
        log.error(f"GCS CSV fetch failed: {e}")
        raise HTTPException(500, f"GCS error: {str(e)}")

def fetch_csv_url(url: str) -> pd.DataFrame:
    """Fetch CSV from URL"""
    log.info(f"Fetching CSV from URL: {url}")
    
    try:
        df = pd.read_csv(url)
        log.info(f"✅ Retrieved {len(df)} rows from URL CSV")
        return df
    except Exception as e:
        log.error(f"URL CSV fetch failed: {e}")
        raise HTTPException(500, f"CSV fetch error: {str(e)}")

def fetch_json_url(url: str) -> pd.DataFrame:
    """Fetch JSON from URL"""
    log.info(f"Fetching JSON from URL: {url}")
    
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict) and "data" in data:
            df = pd.DataFrame(data["data"])
        else:
            df = pd.DataFrame([data])
        
        log.info(f"✅ Retrieved {len(df)} rows from URL JSON")
        return df
    except Exception as e:
        log.error(f"URL JSON fetch failed: {e}")
        raise HTTPException(500, f"JSON fetch error: {str(e)}")

# ------------------------------------------------------------------
# SCHEMA VALIDATION & INFERENCE
# ------------------------------------------------------------------
def infer_schema(df: pd.DataFrame) -> List[ColumnSchema]:
    """Infer schema from DataFrame"""
    schema = []
    
    for col in df.columns:
        dtype = str(df[col].dtype)
        nullable = df[col].isnull().any()
        
        # Map pandas dtype to SQL-like type
        if dtype.startswith("int"):
            col_type = "INTEGER"
        elif dtype.startswith("float"):
            col_type = "FLOAT"
        elif dtype == "bool":
            col_type = "BOOLEAN"
        elif dtype.startswith("datetime"):
            col_type = "TIMESTAMP"
        else:
            col_type = "STRING"
        
        schema.append(ColumnSchema(
            name=col,
            type=col_type,
            nullable=nullable
        ))
    
    return schema

def validate_and_coerce(df: pd.DataFrame) -> tuple[pd.DataFrame, List[str]]:
    """Validate and coerce data types, return warnings"""
    warnings = []
    
    for col in df.columns:
        # Check for mixed types
        if df[col].dtype == "object":
            # Try numeric conversion
            try:
                df[col] = pd.to_numeric(df[col], errors='ignore')
            except:
                pass
        
        # Check for null values
        null_count = df[col].isnull().sum()
        if null_count > 0:
            warnings.append(f"Column '{col}' has {null_count} null values")
        
        # Check for duplicates in potential key columns
        if df[col].nunique() == len(df) and "id" in col.lower():
            # Likely a primary key
            if df[col].duplicated().any():
                warnings.append(f"Column '{col}' appears to be a key but has duplicates")
    
    return df, warnings

# ------------------------------------------------------------------
# MAIN FETCH ENDPOINT
# ------------------------------------------------------------------
@app.post("/fetch_data", response_model=DataResponse)
async def fetch_data(req: DataRequest) -> DataResponse:
    """
    Main data retrieval endpoint
    """
    log.info(f"Data fetch request: {req.source}")
    
    df = None
    
    try:
        # Route to appropriate fetcher
        if req.source == SourceType.BIGQUERY:
            spec = BigQuerySpec(**req.spec) if isinstance(req.spec, dict) else req.spec
            df = fetch_bigquery(spec)
            table_name = "bigquery_result"
            
        elif req.source == SourceType.SHEETS:
            spec = SheetsSpec(**req.spec) if isinstance(req.spec, dict) else req.spec
            df = fetch_sheets(spec)
            table_name = f"sheets_{spec.spreadsheet_id[:8]}"
            
        elif req.source == SourceType.REST_API:
            spec = RestApiSpec(**req.spec) if isinstance(req.spec, dict) else req.spec
            df = fetch_rest_api(spec)
            table_name = "rest_api_result"
            
        elif req.source == SourceType.GCS_CSV:
            uri = req.spec.get("uri") if isinstance(req.spec, dict) else req.spec
            df = fetch_csv_gcs(uri)
            table_name = "gcs_csv_result"
            
        elif req.source == SourceType.URL_CSV:
            url = req.spec.get("url") if isinstance(req.spec, dict) else req.spec
            df = fetch_csv_url(url)
            table_name = "url_csv_result"
            
        elif req.source == SourceType.URL_JSON:
            url = req.spec.get("url") if isinstance(req.spec, dict) else req.spec
            df = fetch_json_url(url)
            table_name = "url_json_result"
        
        else:
            raise HTTPException(400, f"Unsupported source type: {req.source}")
        
        # Validate and coerce
        df, warnings = validate_and_coerce(df)
        
        # Infer schema
        schema = infer_schema(df)
        
        # Generate preview
        preview = df.head(10).to_dict(orient="records")
        
        # For large datasets, save to GCS
        data_path = None
        if len(df) > 10000:
            # Save to GCS
            timestamp = datetime.now(timezone.utc).isoformat()
            filename = f"data_retrieval_{hashlib.md5(timestamp.encode()).hexdigest()[:8]}.parquet"
            data_path = f"gs://{project_id}-data-retrieval/{filename}"
            
            # TODO: Actually upload to GCS
            log.info(f"Large dataset ({len(df)} rows) - would save to {data_path}")
            warnings.append(f"Large dataset: {len(df)} rows. Consider using data_path for downstream processing.")
        
        # Build provenance
        provenance = {
            "source": req.source.value,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "spec": req.spec if isinstance(req.spec, dict) else req.spec.model_dump(),
            "row_count": len(df),
            "column_count": len(df.columns)
        }
        
        log.info(f"✅ Data fetch complete: {len(df)} rows, {len(df.columns)} columns")
        
        return DataResponse(
            table_name=table_name,
            rows=len(df),
            columns=schema,
            preview=preview,
            data_path=data_path,
            provenance=provenance,
            warnings=warnings
        )
        
    except Exception as e:
        log.error(f"Data fetch failed: {e}")
        raise HTTPException(500, f"Data retrieval error: {str(e)}")

# ------------------------------------------------------------------
# UTILITY ENDPOINTS
# ------------------------------------------------------------------
@app.get("/")
async def root():
    return {
        "agent": "data_retriever",
        "status": "operational",
        "version": "1.0.0",
        "supported_sources": [s.value for s in SourceType]
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "bigquery": bool(bq_client),
        "sheets": bool(sheets_service),
        "gcs": bool(storage_client)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
