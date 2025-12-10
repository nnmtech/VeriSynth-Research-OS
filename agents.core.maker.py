# agents/core/maker.py
from __future__ import annotations
import json
import logging
import os
from collections import defaultdict
from typing import Any, Callable, Dict, Optional, TypeVar
from pydantic import BaseModel, ValidationError

log = logging.getLogger("maker")
T = TypeVar("T")

class RedFlagError(Exception):
    """Raised when response is pathological and must be discarded."""

def strict_json_parser(response: str, model: type[BaseModel]) -> BaseModel:
    """Parse + validate in one shot – any failure → RedFlagError (no repair)."""
    try:
        # More robust: find the last complete JSON object in the stream
        # Handles cases where LLM adds extra text after closing brace
        brace_count = 0
        end = -1
        for i in range(len(response) - 1, -1, -1):
            if response[i] == '}':
                if brace_count == 0:
                    end = i + 1
                brace_count += 1
            elif response[i] == '{':
                brace_count -= 1
                if brace_count == 0 and end != -1:
                    start = i
                    data = json.loads(response[start:end])
                    return model.model_validate(data)
        raise ValueError("No complete JSON object found")
    except (json.JSONDecodeError, ValidationError, ValueError) as e:
        log.debug("Red-flagging response (invalid JSON/schema): %s | Response preview: %.200s", e, response)
        raise RedFlagError("Invalid format or schema") from e

def first_to_ahead_by_k(
    task_input: Dict[str, Any],
    sampler: Callable[[Dict[str, Any]], str],
    parser: Callable[[str], T],
    k: int = 3,
    max_rounds: int = 40,
    max_tokens: Optional[int] = None,
) -> T:
    """
    Exact algorithm from MAKER paper (Algorithm 2 + red-flagging).
    Returns the winning candidate the moment it is ahead by k votes.
    """
    # Dynamic red-flag threshold — the tiny improvement used in production
    if max_tokens is None:
        model_name = task_input.get("model") or os.getenv("LLM_MODEL", "").lower()
        if any(m in model_name for m in ["o1", "claude-3", "grok", "sonnet", "opus", "haiku"]):
            max_tokens = 1200
        else:
            max_tokens = 750  # safe default for mini/nano models

    votes: Dict[str, int] = defaultdict(int)
    best: Optional[str] = None

    for round_num in range(1, max_rounds + 1):
        raw = sampler(task_input)

        if len(raw) > max_tokens:
            log.debug("Round %d: red-flagged (too long: %d > %d tokens)", round_num, len(raw), max_tokens)
            continue

        try:
            parsed = parser(raw)
            # Canonical serialization for exact equality
            if isinstance(parsed, BaseModel):
                serialized = json.dumps(parsed.model_dump(), sort_keys=True, ensure_ascii=False)
            else:
                serialized = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
        except RedFlagError:
            continue

        votes[serialized] += 1
        current_count = votes[serialized]

        # First-to-ahead-by-k condition
        if best is None or current_count >= k + max((votes[v] for v in votes if v != serialized), default=0):
            log.info("Winner decided in round %d with %d votes (k=%d, model=%s)", 
                     round_num, current_count, k, task_input.get("model", "unknown"))
            return parsed

        if votes[serialized] > votes.get(best or "", 0):
            best = serialized

    raise RuntimeError(f"MAKER voting failed to converge after {max_rounds} rounds — increase max_rounds or k")
