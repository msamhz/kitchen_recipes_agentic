import os
import anthropic
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

load_dotenv()

_api_key = os.environ["ANTHROPIC_API_KEY"]

# Lambda has proper certs; local dev may have Norton SSL interception
if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    sync_client = anthropic.Anthropic(api_key=_api_key)
    async_client = AsyncAnthropic(api_key=_api_key)
else:
    import httpx
    sync_client = anthropic.Anthropic(
        api_key=_api_key,
        http_client=httpx.Client(verify=False),
    )
    async_client = AsyncAnthropic(
        api_key=_api_key,
        http_client=httpx.AsyncClient(verify=False),
    )
