# agents/transformer/agent.py
"""
VeriSynthOS Transformer Agent - REST API
Purpose: Data cleaning, normalization, and ETL with MAKER voting
"""

import logging
from agents.core.maker import first_to_ahead_by_k, strict_json_parser
from agents.core.llm_router import llm_call
from pydantic import BaseModel
from typing import Any

from fastapi import FastAPI, HTTPException

log = logging.getLogger("transformer")
log.setLevel(logging.INFO)

app = FastAPI(title="VeriSynthOS Transformer Agent")

class TransformationPlan(BaseModel):
    # Your actual schema — whatever you use for cleaning/normalizing
    steps: list[dict]
    output_schema: dict
    provenance: dict

class TransformRequest(BaseModel):
    data_path: str
    spec: dict

def build_transform_prompt(data_path: str, spec: dict) -> str:
    """Build transformation prompt from data path and spec."""
    return f"Transform data at {data_path} using spec: {spec}"

def execute_plan_safely(plan: TransformationPlan) -> Any:
    """Execute the transformation plan safely with pandas/BigQuery."""
    import pandas as pd
    import numpy as np
    from google.cloud import bigquery
    import google.auth
    
    log.info(f"Executing transformation plan with {len(plan.steps)} steps")
    
    try:
        # Load data
        data_path = plan.provenance.get("data_path")
        if not data_path:
            raise ValueError("No data_path in transformation plan")
        
        # Support multiple formats
        if data_path.endswith(".csv"):
            df = pd.read_csv(data_path)
        elif data_path.endswith(".parquet"):
            df = pd.read_parquet(data_path)
        elif data_path.endswith(".json"):
            df = pd.read_json(data_path)
        else:
            raise ValueError(f"Unsupported file format: {data_path}")
        
        log.info(f"Loaded {len(df)} rows from {data_path}")
        
        # Execute each transformation step
        for i, step in enumerate(plan.steps):
            step_type = step.get("type")
            log.info(f"Step {i+1}: {step_type}")
            
            if step_type == "rename":
                df = df.rename(columns=step.get("mapping", {}))
            
            elif step_type == "convert":
                # Type conversions
                for col, target_type in step.get("conversions", {}).items():
                    if col in df.columns:
                        try:
                            if target_type == "int":
                                df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
                            elif target_type == "float":
                                df[col] = pd.to_numeric(df[col], errors='coerce')
                            elif target_type == "datetime":
                                df[col] = pd.to_datetime(df[col], errors='coerce')
                            elif target_type == "string":
                                df[col] = df[col].astype(str)
                        except Exception as e:
                            log.warning(f"Failed to convert {col} to {target_type}: {e}")
            
            elif step_type == "dedupe":
                keys = step.get("keys", [])
                if keys:
                    before = len(df)
                    df = df.drop_duplicates(subset=keys)
                    log.info(f"Removed {before - len(df)} duplicates")
            
            elif step_type == "fillna":
                fill_values = step.get("fill_values", {})
                df = df.fillna(fill_values)
            
            elif step_type == "filter":
                # Apply row filters
                query = step.get("query")
                if query:
                    df = df.query(query)
            
            elif step_type == "aggregate":
                # Group by and aggregate
                group_by = step.get("group_by", [])
                agg_funcs = step.get("aggregations", {})
                if group_by and agg_funcs:
                    df = df.groupby(group_by).agg(agg_funcs).reset_index()
            
            elif step_type == "derive":
                # Create derived columns
                for col_name, expression in step.get("columns", {}).items():
                    try:
                        df[col_name] = df.eval(expression)
                    except Exception as e:
                        log.warning(f"Failed to create derived column {col_name}: {e}")
        
        # Save transformed data
        output_path = data_path.replace(".csv", "_transformed.csv").replace(".parquet", "_transformed.parquet")
        
        if output_path.endswith(".parquet"):
            df.to_parquet(output_path, index=False)
        else:
            df.to_csv(output_path, index=False)
        
        log.info(f"✅ Transformation complete: {len(df)} rows -> {output_path}")
        
        return {
            "status": "success",
            "output_path": output_path,
            "rows": len(df),
            "columns": list(df.columns),
            "plan": plan.model_dump()
        }
        
    except Exception as e:
        log.error(f"Transformation failed: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "plan": plan.model_dump()
        }

def transform_maker(data_path: str, spec: dict) -> Any:
    def sampler(task_input: dict) -> str:
        prompt = build_transform_prompt(data_path, spec)
        return llm_call(
            prompt=prompt,
            system_prompt="You are a precise data transformer. Return ONLY valid JSON matching TransformationPlan. No explanations.",
            temperature=0.0,      # ← Critical: transformations must be deterministic
            max_tokens=1600       # ← Transform specs are longer than verification/export
        )

    parsed = first_to_ahead_by_k(
        task_input={"data_path": data_path, "spec": spec},  # ← Pass real context
        sampler=sampler,
        parser=lambda raw: strict_json_parser(raw, TransformationPlan),
        k=3,
        max_tokens=None,  # ← Use dynamic threshold from maker.py (auto 750 or 1200)
    )
    return execute_plan_safely(parsed)

# REST API Endpoints
@app.post("/transform")
async def transform(req: TransformRequest):
    """
    Transform data with MAKER voting
    """
    log.info(f"Transforming data: {req.data_path}")
    
    try:
        result = transform_maker(req.data_path, req.spec)
        
        log.info(f"✅ Transformation complete")
        
        return result
    
    except Exception as e:
        log.error(f"Transformation failed: {e}")
        raise HTTPException(500, f"Transformation error: {str(e)}")

@app.get("/")
async def root():
    return {
        "agent": "transformer",
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
    uvicorn.run(app, host="0.0.0.0", port=8004)
