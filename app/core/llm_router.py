"""
LLM Router for VeriSynth Research OS.

Supports OpenAI, Anthropic Claude, Grok, and Ollama with unified interface.
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

import httpx
import structlog
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.core.config import get_settings

logger = structlog.get_logger(__name__)


class LLMProvider(str, Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GROK = "grok"
    OLLAMA = "ollama"


class LLMMessage:
    """Unified message format across providers."""

    def __init__(self, role: str, content: str) -> None:
        """Initialize message."""
        self.role = role
        self.content = content

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary."""
        return {"role": self.role, "content": self.content}


class LLMResponse:
    """Unified response format across providers."""

    def __init__(
        self,
        content: str,
        model: str,
        provider: LLMProvider,
        usage: dict[str, int],
        raw_response: Any = None,
    ) -> None:
        """Initialize response."""
        self.content = content
        self.model = model
        self.provider = provider
        self.usage = usage
        self.raw_response = raw_response


class BaseLLMClient(ABC):
    """Base class for LLM clients."""

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate completion."""
        pass


class OpenAIClient(BaseLLMClient):
    """OpenAI API client."""

    def __init__(self, api_key: str) -> None:
        """Initialize OpenAI client."""
        self.client = AsyncOpenAI(api_key=api_key)
        self.logger = logger.bind(provider="openai")

    async def complete(
        self,
        messages: list[LLMMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate completion using OpenAI."""
        self.logger.debug("openai_request", model=model, num_messages=len(messages))

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=[msg.to_dict() for msg in messages],
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

            content = response.choices[0].message.content or ""
            usage = {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            }

            self.logger.info("openai_success", model=model, tokens=usage["total_tokens"])

            return LLMResponse(
                content=content,
                model=model,
                provider=LLMProvider.OPENAI,
                usage=usage,
                raw_response=response,
            )
        except Exception as e:
            self.logger.error("openai_error", error=str(e))
            raise


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude API client."""

    def __init__(self, api_key: str) -> None:
        """Initialize Anthropic client."""
        self.client = AsyncAnthropic(api_key=api_key)
        self.logger = logger.bind(provider="anthropic")

    async def complete(
        self,
        messages: list[LLMMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate completion using Anthropic Claude."""
        self.logger.debug("anthropic_request", model=model, num_messages=len(messages))

        try:
            # Convert messages - extract system message if present
            system_message = None
            claude_messages = []

            for msg in messages:
                if msg.role == "system":
                    system_message = msg.content
                else:
                    claude_messages.append(msg.to_dict())

            request_params: dict[str, Any] = {
                "model": model,
                "messages": claude_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                **kwargs,
            }

            if system_message:
                request_params["system"] = system_message

            response = await self.client.messages.create(**request_params)

            # Safely extract content with bounds checking
            content = ""
            if response.content and len(response.content) > 0:
                content = response.content[0].text

            usage = {
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            }

            self.logger.info("anthropic_success", model=model, tokens=usage["total_tokens"])

            return LLMResponse(
                content=content,
                model=model,
                provider=LLMProvider.ANTHROPIC,
                usage=usage,
                raw_response=response,
            )
        except Exception as e:
            self.logger.error("anthropic_error", error=str(e))
            raise


class GrokClient(BaseLLMClient):
    """Grok API client (X.AI)."""

    def __init__(self, api_key: str) -> None:
        """Initialize Grok client."""
        self.api_key = api_key
        self.base_url = "https://api.x.ai/v1"
        self.logger = logger.bind(provider="grok")

    async def complete(
        self,
        messages: list[LLMMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate completion using Grok."""
        self.logger.debug("grok_request", model=model, num_messages=len(messages))

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [msg.to_dict() for msg in messages],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        **kwargs,
                    },
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()

            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})

            self.logger.info("grok_success", model=model, tokens=usage.get("total_tokens", 0))

            return LLMResponse(
                content=content,
                model=model,
                provider=LLMProvider.GROK,
                usage={
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
                raw_response=data,
            )
        except Exception as e:
            self.logger.error("grok_error", error=str(e))
            raise


class OllamaClient(BaseLLMClient):
    """Ollama local API client."""

    def __init__(self, base_url: str) -> None:
        """Initialize Ollama client."""
        self.base_url = base_url
        self.logger = logger.bind(provider="ollama")

    async def complete(
        self,
        messages: list[LLMMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate completion using Ollama."""
        self.logger.debug("ollama_request", model=model, num_messages=len(messages))

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": model,
                        "messages": [msg.to_dict() for msg in messages],
                        "stream": False,
                        "options": {
                            "temperature": temperature,
                            "num_predict": max_tokens,
                        },
                    },
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()

            content = data["message"]["content"]

            self.logger.info("ollama_success", model=model)

            return LLMResponse(
                content=content,
                model=model,
                provider=LLMProvider.OLLAMA,
                usage={
                    "prompt_tokens": 0,  # Ollama doesn't provide token counts
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
                raw_response=data,
            )
        except Exception as e:
            self.logger.error("ollama_error", error=str(e))
            raise


class LLMRouter:
    """
    LLM Router for unified access to multiple LLM providers.

    Supports OpenAI, Anthropic Claude, Grok, and Ollama.
    """

    def __init__(self) -> None:
        """Initialize LLM router with configured providers."""
        self.settings = get_settings()
        self.clients: dict[LLMProvider, BaseLLMClient] = {}
        self.logger = logger.bind(component="llm_router")

        # Initialize available clients
        if self.settings.openai_api_key:
            self.clients[LLMProvider.OPENAI] = OpenAIClient(self.settings.openai_api_key)
            self.logger.info("initialized_provider", provider="openai")

        if self.settings.anthropic_api_key:
            self.clients[LLMProvider.ANTHROPIC] = AnthropicClient(
                self.settings.anthropic_api_key
            )
            self.logger.info("initialized_provider", provider="anthropic")

        if self.settings.grok_api_key:
            self.clients[LLMProvider.GROK] = GrokClient(self.settings.grok_api_key)
            self.logger.info("initialized_provider", provider="grok")

        # Ollama is always available (falls back to localhost)
        self.clients[LLMProvider.OLLAMA] = OllamaClient(self.settings.ollama_base_url)
        self.logger.info("initialized_provider", provider="ollama")

    async def complete(
        self,
        messages: list[LLMMessage],
        provider: LLMProvider | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Generate completion using specified or default provider.

        Args:
            messages: List of messages
            provider: LLM provider to use (defaults to configured default)
            model: Model to use (defaults to provider's default)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific parameters

        Returns:
            LLMResponse with generated content
        """
        # Determine provider
        if provider is None:
            provider = LLMProvider(self.settings.default_llm_provider)

        if provider not in self.clients:
            raise ValueError(f"Provider {provider} not configured")

        # Determine model
        if model is None:
            model = self.settings.default_llm_model

        self.logger.info(
            "routing_request",
            provider=provider,
            model=model,
            num_messages=len(messages),
        )

        client = self.clients[provider]

        try:
            response = await client.complete(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            return response
        except Exception as e:
            self.logger.error("completion_error", provider=provider, error=str(e))
            raise

    async def complete_with_fallback(
        self,
        messages: list[LLMMessage],
        providers: list[LLMProvider],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Try multiple providers with fallback on failure.

        Args:
            messages: List of messages
            providers: List of providers to try in order
            model: Model to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional parameters

        Returns:
            LLMResponse from first successful provider

        Raises:
            RuntimeError if all providers fail
        """
        errors: list[str] = []

        for provider in providers:
            if provider not in self.clients:
                self.logger.warning("provider_not_available", provider=provider)
                continue

            try:
                self.logger.debug("trying_provider", provider=provider)
                return await self.complete(
                    messages=messages,
                    provider=provider,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            except Exception as e:
                error_msg = f"{provider}: {str(e)}"
                errors.append(error_msg)
                self.logger.warning("provider_failed", provider=provider, error=str(e))

        raise RuntimeError(f"All providers failed: {', '.join(errors)}")

    def get_available_providers(self) -> list[LLMProvider]:
        """Get list of available providers."""
        return list(self.clients.keys())
