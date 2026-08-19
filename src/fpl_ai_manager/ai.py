from __future__ import annotations

import os
from openai import OpenAI
from .prompting import SYSTEM, build_prompt


def recommend(payload: dict) -> str:
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model = os.getenv("OPENAI_MODEL", "gpt-5")
    use_web = os.getenv("OPENAI_WEB_SEARCH", "true").lower() in {"1", "true", "yes"}
    kwargs = {
        "model": model,
        "instructions": SYSTEM,
        "input": build_prompt(payload),
    }
    if use_web:
        kwargs["tools"] = [{"type": "web_search"}]
    response = client.responses.create(**kwargs)
    return response.output_text
