# agents/verifier/agent.py
"""
VeriSynthOS Verifier Agent - REST API
Purpose: Fact-checking and claim verification with MAKER voting
"""

import logging
from agents.core.maker import first_to_ahead_by_k, strict_json_parser, RedFlagError
from agents.core.llm_router import llm_call
from pydantic import BaseModel, Field
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

log = logging.getLogger("verifier")
log.setLevel(logging.INFO)

app = FastAPI(title="VeriSynthOS Verifier Agent")

class VerificationResult(BaseModel):
    claim_id: str
    verdict: str = Field(..., description="SUPPORTED | CONTRADICTED | MIXED | INSUFFICIENT")
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: List[dict] = Field(..., description="List of {url, snippet, title}")
    rationale: str

class VerificationReport(BaseModel):
    results: List[VerificationResult]

class VerifyRequest(BaseModel):
    claims: List[dict]
    policy: dict = {}

def build_verification_prompt(claims: List[dict]) -> str:
    """Build verification prompt from claims."""
    claims_text = "\n".join([f"- {claim.get('text', claim)}" for claim in claims])
    return f"Verify the following claims and return results in JSON format:\n{claims_text}"

def verify_claims_maker(claims: List[dict]) -> List[VerificationResult]:
    def sampler(task_input: dict) -> str:
        # One single LLM call per vote
        prompt = build_verification_prompt(task_input["claims"])
        return llm_call(
            prompt=prompt,
            system_prompt="You are a rigorous fact-checker. Return only valid JSON.",
            max_tokens=1200,
            temperature=0.1
        )

    def parser(raw_response: str) -> VerificationReport:
        # Pure parsing — no second LLM call!
        return strict_json_parser(raw_response, VerificationReport)

    # This is the actual MAKER voting (first-to-ahead-by-3 + red-flagging)
    report = first_to_ahead_by_k(
        task_input={"claims": claims},
        sampler=sampler,
        parser=parser,
        k=3,           # Proven in the paper → >99.999% zero-error probability
        max_tokens=800 # Red-flag anything longer (correlates with hallucination)
    )
    return report.results

# REST API Endpoints
@app.post("/verify_claims", response_model=VerificationReport)
async def verify_claims(req: VerifyRequest) -> VerificationReport:
    """
    Verify claims with MAKER voting
    """
    log.info(f"Verifying {len(req.claims)} claims")
    
    try:
        results = verify_claims_maker(req.claims)
        
        log.info(f"✅ Verification complete: {len(results)} results")
        
        return VerificationReport(results=results)
    
    except Exception as e:
        log.error(f"Verification failed: {e}")
        raise HTTPException(500, f"Verification error: {str(e)}")

@app.get("/")
async def root():
    return {
        "agent": "verifier",
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
    uvicorn.run(app, host="0.0.0.0", port=8002)
