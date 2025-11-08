# rate_limiter.py
import os
import asyncio
import time
from typing import Union, Optional, List, Dict, Any
from rich import print
from openai import OpenAI
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class TokenManager:
    MODEL_LIMITS = {
        # Replace these with your real dashboard values
        "gpt-4o-mini": {"tpm": 60_000, "rpm": 3},
        "default": {"tpm": 60_000, "rpm": 3},
    }

    def __init__(self, model_name="gpt-4o-mini"):
        self._model_name = model_name
        limits = self.MODEL_LIMITS.get(model_name, self.MODEL_LIMITS["default"])
        self._TPM_LIMIT = limits["tpm"]
        self._RPM_LIMIT = limits["rpm"]

        self._TPM_THRESHOLD = self._TPM_LIMIT * 0.9
        self._RPM_THRESHOLD = self._RPM_LIMIT * 0.9

        self._current_tokens = 0
        self._current_requests = 0
        self._last_reset_time = time.time()
        self._token_lock = asyncio.Lock()

    async def manage_rate_limits(self, usage: dict):
        async with self._token_lock:
            now = time.time()

            # Reset counters if a minute has passed
            if now - self._last_reset_time >= 60:
                self._current_tokens = 0
                self._current_requests = 0
                self._last_reset_time = now

            tokens_used = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
            self._current_tokens += tokens_used
            self._current_requests += 1

            print(f"[dim]Requests: {self._current_requests}/{self._RPM_LIMIT}[/dim]")
            print(f"[dim]Tokens: {self._current_tokens}/{self._TPM_LIMIT}[/dim]")

            time_left = 60 - (now - self._last_reset_time)
            if self._current_requests >= self._RPM_THRESHOLD or self._current_tokens >= self._TPM_THRESHOLD:
                if time_left > 0:
                    print(f"[bold yellow]Near OpenAI rate limit. Sleeping {time_left:.2f}s...[/bold yellow]")
                    await asyncio.sleep(time_left + 1)


# Shared limiter instance
shared_rate_limiter = TokenManager(model_name="gpt-4o-mini")


async def call_llm_with_limit(
    messages: List[Dict[str, Any]],
    model_name: str = "gpt-4o-mini",
    schema_model: Optional[BaseModel] = None,
    temperature: float = 0.0
):
    """
    Centralized async helper for calling OpenAI LLM with shared rate limiting.

    Args:
        messages: List of message dicts for Chat Completions.
        model_name: OpenAI model name.
        schema_model: Optional Pydantic BaseModel for structured output.
        temperature: Sampling temperature.
    
    Returns:
        OpenAI completion object (with parsed result if schema_model provided).
    """
    if schema_model:
        # Structured output request
        completion = await asyncio.to_thread(
            client.beta.chat.completions.parse,
            model=model_name,
            messages=messages,
            response_format=schema_model,
            temperature=temperature
        )
    else:
        # Plain text chat
        completion = await asyncio.to_thread(
            client.chat.completions.create,
            model=model_name,
            messages=messages,
            temperature=temperature
        )

    # Apply rate limit tracking
    await shared_rate_limiter.manage_rate_limits(completion.usage.to_dict())
    return completion