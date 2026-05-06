from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class LLMResult:
    text: str
    used_model: str
    provider: str


class CloudLLMClient:
    def __init__(self, model: str = "gpt-4o-mini", timeout_s: float = 10.0, max_retries: int = 2) -> None:
        self.model = model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()

    def generate(self, system_prompt: str, user_prompt: str) -> LLMResult:
        if not self.api_key:
            return LLMResult(
                text="LLM not configured (missing OPENAI_API_KEY). Returning grounded data-only summary.",
                used_model="none",
                provider="none",
            )

        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key, timeout=self.timeout_s, max_retries=self.max_retries)
            response = client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_output_tokens=400,
            )
            output_text = response.output_text.strip()
            if not output_text:
                raise ValueError("Empty model output")
            return LLMResult(text=output_text, used_model=self.model, provider="openai")
        except Exception as exc:  # pragma: no cover
            return LLMResult(
                text=f"LLM call failed ({type(exc).__name__}). Returning grounded data-only summary.",
                used_model=self.model,
                provider="openai",
            )
