"""
Anthropic client factory.

Set MOCK_CLAUDE=1 in your environment (or .env) to run without a real API key.
The stub returns plausible canned JSON so the app works fully offline.
"""

import json
import os

from dotenv import load_dotenv

load_dotenv()

_MOCK = os.environ.get("MOCK_CLAUDE", "").strip() == "1"


# ---------------------------------------------------------------------------
# Stub — duck-types the real Anthropic response objects
# ---------------------------------------------------------------------------

class _StubContent:
    def __init__(self, text: str):
        self.text = text


class _StubResponse:
    def __init__(self, text: str):
        self.content = [_StubContent(text)]


def _canned_text(prompt_fragment: str) -> str:
    if "deduplication" in prompt_fragment and "match_index" in prompt_fragment:
        return json.dumps({"match_index": None, "canonical": None})
    if "recipe parser" in prompt_fragment.lower() or "recipe text" in prompt_fragment.lower():
        return json.dumps({
            "name": "Mock Recipe",
            "instructions": "Mock recipe — MOCK_CLAUDE=1 is set.",
            "source": None,
            "ingredients": [
                {"name": "garlic", "is_optional": False},
                {"name": "onion", "is_optional": False},
                {"name": "oil", "is_optional": False},
            ],
        })
    if "difficulty" in prompt_fragment and "prep_time" in prompt_fragment:
        return json.dumps({"difficulty": "easy", "prep_time": "under_10"})
    return json.dumps({
        "ingredients": [
            {"name": "garlic", "confidence": "high", "notes": "", "expiry_date": None},
            {"name": "onion", "confidence": "high", "notes": "", "expiry_date": None},
            {"name": "soy sauce", "confidence": "high", "notes": "", "expiry_date": None},
        ],
        "uncertain": [],
    })


def _extract_prompt(messages: list) -> str:
    text = ""
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            text += content
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text += part.get("text", "")
    return text


class _MockSyncMessages:
    def create(self, *, messages, **kwargs):
        return _StubResponse(_canned_text(_extract_prompt(messages)))


class _MockAsyncMessages:
    async def create(self, *, messages, **kwargs):
        return _StubResponse(_canned_text(_extract_prompt(messages)))


class _MockSyncClient:
    messages = _MockSyncMessages()


class _MockAsyncClient:
    messages = _MockAsyncMessages()


# ---------------------------------------------------------------------------
# Real clients (built lazily only when MOCK_CLAUDE is not set)
# ---------------------------------------------------------------------------

def _build_real_clients():
    import anthropic
    from anthropic import AsyncAnthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. "
            "Set it in .env or use MOCK_CLAUDE=1 to run without a real key."
        )

    # Lambda has proper certs; local dev may have Norton SSL interception
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return anthropic.Anthropic(api_key=api_key), AsyncAnthropic(api_key=api_key)

    import httpx
    return (
        anthropic.Anthropic(api_key=api_key, http_client=httpx.Client(verify=False)),
        AsyncAnthropic(api_key=api_key, http_client=httpx.AsyncClient(verify=False)),
    )


if _MOCK:
    sync_client = _MockSyncClient()
    async_client = _MockAsyncClient()
else:
    sync_client, async_client = _build_real_clients()
