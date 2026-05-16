"""
Shared Anthropic client instances with SSL verification disabled.
Required on machines with corporate/custom certificate chains.
Import from here instead of instantiating clients directly in each tool.
"""

import os
import httpx
import anthropic
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

load_dotenv()

_api_key = os.environ["ANTHROPIC_API_KEY"]

sync_client = anthropic.Anthropic(
    api_key=_api_key,
    http_client=httpx.Client(verify=False),
)

async_client = AsyncAnthropic(
    api_key=_api_key,
    http_client=httpx.AsyncClient(verify=False),
)
