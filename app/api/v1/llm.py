"""LLM router API endpoints."""

from fastapi import APIRouter, HTTPException

from app.core.llm_router import LLMMessage, LLMProvider, LLMRouter
from app.models.schemas import LLMRequest
from app.models.schemas import LLMResponse as LLMResponseSchema

router = APIRouter()
llm_router = LLMRouter()


@router.post("/complete", response_model=LLMResponseSchema)
async def complete(request: LLMRequest) -> LLMResponseSchema:
    """Generate LLM completion."""
    try:
        # Convert request messages to LLMMessage objects
        messages = [
            LLMMessage(role=msg["role"], content=msg["content"])
            for msg in request.messages
        ]

        # Get provider
        provider: LLMProvider | None = None
        if request.provider:
            provider = LLMProvider(request.provider)

        # Generate completion
        response = await llm_router.complete(
            messages=messages,
            provider=provider,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )

        return LLMResponseSchema(
            content=response.content,
            model=response.model,
            provider=response.provider.value,
            usage=response.usage,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/providers")
async def get_providers() -> dict[str, list[str]]:
    """Get available LLM providers."""
    providers = llm_router.get_available_providers()
    return {"providers": [p.value for p in providers]}
