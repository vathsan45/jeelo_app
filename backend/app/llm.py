"""Groq LLM wrapper: strict-JSON calls, one retry, key rotation on failures.

Every LLM feature in the app (failure testing, coach report) goes through
call_llm_json(). Returns a dict on success or None after retries are
exhausted — callers must always have a non-LLM fallback path.
"""

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_KEYS = [
    k.strip()
    for k in os.environ.get("GROQ_API_KEYS", os.environ.get("GROQ_API_KEY", "")).split(",")
    if k.strip()
]
MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

_key_idx = 0


def _parse_json(text):
    """Parse model output as JSON, tolerating markdown fences and prose wrap."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            return json.loads(brace.group(0))
        raise


def call_llm_json(system_prompt, user_message, max_retries=1, temperature=0.4):
    """One Groq chat call expecting strict JSON output.

    Retries once on parse failure; rotates to the next API key on transport /
    rate-limit errors. Returns dict, or None if everything failed.
    """
    global _key_idx
    if not _KEYS:
        return None

    for attempt in range(max_retries + 1):
        try:
            client = Groq(api_key=_KEYS[_key_idx % len(_KEYS)])
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            return _parse_json(resp.choices[0].message.content)
        except (json.JSONDecodeError, IndexError, KeyError):
            continue  # bad output — retry with same key
        except Exception:
            _key_idx += 1  # rate limit / auth / network — rotate key and retry
            continue
    return None
