# agents/core/llm_router.py
import os
from typing import Optional
import ollama
from xai_sdk import Client as GrokClient
from xai_sdk.chat import system, user  # ← NEW: Explicit import for Grok helpers
from anthropic import Anthropic
from openai import OpenAI  # Assuming existing OpenAI integration

PROVIDER = os.getenv("LLM_PROVIDER", "OPENAI")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
API_KEYS = {
    "OPENAI": os.getenv("OPENAI_API_KEY"),
    "GROK": os.getenv("XAI_API_KEY"),
    "CLAUDE": os.getenv("ANTHROPIC_API_KEY"),
}

def llm_call(prompt: str, system_prompt: Optional[str] = None, max_tokens: int = 1024, temperature: float = 0.1) -> str:
    """Unified interface for all providers. Returns generated text."""
    if not API_KEYS.get(PROVIDER):
        raise ValueError(f"Missing API key for provider: {PROVIDER}")

    messages = [{"role": "user", "content": prompt}]
    if system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})

    if PROVIDER == "OPENAI":
        client = OpenAI(api_key=API_KEYS["OPENAI"])
        response = client.chat.completions.create(
            model=MODEL, messages=messages, max_tokens=max_tokens, temperature=temperature
        )
        return response.choices[0].message.content or ""

    elif PROVIDER == "OLLAMA":
        response = ollama.chat(
            model=MODEL, messages=messages, options={"num_predict": max_tokens, "temperature": temperature}
        )
        return response["message"]["content"] or ""

    elif PROVIDER == "GROK":
        client = GrokClient(api_key=API_KEYS["GROK"])
        chat = client.chat.create(model=MODEL)
        if system_prompt:
            chat.append(system(system_prompt))
        chat.append(user(prompt))
        response = chat.sample(max_tokens=max_tokens, temperature=temperature)
        return response.content or ""

    elif PROVIDER == "CLAUDE":
        client = Anthropic(api_key=API_KEYS["CLAUDE"])
        if system_prompt:
            response = client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}]
            )
        else:
            response = client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}]
            )
        return response.content[0].text or ""

    else:
        raise ValueError(f"Unsupported provider: {PROVIDER}")
