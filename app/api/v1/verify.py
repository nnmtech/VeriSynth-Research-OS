"""Verification agent API endpoints."""
from fastapi import APIRouter, HTTPException

from app.agents.verifier import VerifierAgent
from app.models.schemas import VerificationRequest, VerificationResult

router = APIRouter()
verifier_agent = VerifierAgent()


@router.post("/", response_model=VerificationResult)
async def verify_content(
    request: VerificationRequest,
    num_verifiers: int = 3,
) -> VerificationResult:
    """Verify content using multiple verifiers with voting."""
    try:
        return await verifier_agent.verify(request, num_verifiers=num_verifiers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
