"""Provider errors are mapped without leaking response bodies or credentials."""

import groq
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..guards import strict_json
from .tools import ToolRequest, definitions


class ProviderError(Exception):
    def __init__(self, message: str, status: int = 502):
        self.message = message
        self.status = status
        super().__init__(message)


class Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(default="", max_length=12000)
    calls: list[ToolRequest] = Field(default_factory=list, max_length=10)


async def read_bounded(response):
    """Bound decompressed response bytes while reading, before JSON/schema parsing."""
    if response.headers.get("content-encoding", "identity").lower() != "identity":
        raise ProviderError("Unsupported provider response encoding")
    length = response.headers.get("content-length", "")
    if length.isdigit() and int(length) > 100000:
        raise ProviderError("Provider response exceeded the size limit")
    body = bytearray()
    async for chunk in (
        response.aiter_bytes(chunk_size=8192)
        if hasattr(response, "aiter_bytes")
        else response.iter_bytes(chunk_size=8192)
    ):
        if len(body) + len(chunk) > 100000:
            raise ProviderError("Provider response exceeded the size limit")
        body.extend(chunk)
    return strict_json(bytes(body))


def reply_from(message, groq_arguments=False):
    return Reply(
        content=message.get("content") or "",
        calls=[
            ToolRequest(
                name=c["function"]["name"],
                arguments=strict_json(c["function"]["arguments"])
                if groq_arguments
                else c["function"]["arguments"],
            )
            for c in message.get("tool_calls") or []
        ],
    )


class Providers:
    def __init__(self, settings):
        self.settings = settings

    async def complete(
        self, provider: str, model: str, messages: list[dict], allowed: list[str]
    ) -> Reply:
        s = self.settings
        try:
            if provider not in ("groq", "ollama"):
                raise ProviderError("Provider is not permitted", 422)
            if provider == "groq":
                if not s.groq_api_key.get_secret_value():
                    raise ProviderError(
                        "Groq is not configured. Set GROQ_API_KEY on the backend.", 503
                    )
                async with groq.AsyncGroq(
                    api_key=s.groq_api_key.get_secret_value(),
                    timeout=s.agent_provider_timeout,
                    max_retries=0,
                    base_url="https://api.groq.com",
                    default_headers={"Accept-Encoding": "identity"},
                    http_client=groq.DefaultAsyncHttpxClient(follow_redirects=False),
                ) as client:
                    # Explicit availability check; no silent model or provider fallback.
                    async with client.models.with_streaming_response.retrieve(
                        model
                    ) as response:
                        await read_bounded(response)
                    async with client.chat.completions.with_streaming_response.create(
                        model=model,
                        messages=messages,
                        tools=definitions(allowed) or None,
                        max_completion_tokens=1024,
                        temperature=0.2,
                    ) as response:
                        result = await read_bounded(response)
                    return reply_from(
                        result["choices"][0]["message"], groq_arguments=True
                    )
            if not s.ollama_enabled:
                raise ProviderError(
                    "Ollama is disabled. Enable it explicitly to use a local model.",
                    503,
                )
            # URL is operator-configured and restricted to loopback; never supplied by users/models.
            async with httpx.AsyncClient(
                base_url=s.ollama_url.replace("localhost", "127.0.0.1"),
                timeout=s.agent_provider_timeout,
                trust_env=False,
                follow_redirects=False,
                headers={"Accept-Encoding": "identity"},
            ) as client:
                async with client.stream("GET", "/api/tags") as response:
                    response.raise_for_status()
                    tags = await read_bounded(response)
                if model not in [m["name"] for m in tags.get("models", [])]:
                    raise ProviderError(
                        "The selected Ollama model is not installed. No model was downloaded.",
                        422,
                    )
                async with client.stream(
                    "POST",
                    "/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "tools": definitions(allowed),
                        "stream": False,
                        "keep_alive": "1m",
                        "options": {"num_ctx": 4096, "num_predict": 1024},
                    },
                ) as response:
                    response.raise_for_status()
                    result = await read_bounded(response)
                return reply_from(result["message"])
        except groq.AuthenticationError:
            raise ProviderError(
                "Groq rejected the API credentials. Check the backend key.", 503
            ) from None
        except groq.RateLimitError:
            raise ProviderError(
                "Groq rate limit reached. Wait before retrying; free-tier limits apply.",
                429,
            ) from None
        except (groq.APITimeoutError, httpx.TimeoutException):
            raise ProviderError(
                "The model provider timed out. Please retry later.", 504
            ) from None
        except groq.NotFoundError:
            raise ProviderError(
                "The selected Groq model is unavailable. Check GROQ_MODEL.", 422
            ) from None
        except (groq.APIConnectionError, httpx.ConnectError):
            raise ProviderError(
                "The model provider is unreachable. Check service availability.", 503
            ) from None
        except groq.APIStatusError:
            raise ProviderError(
                "Groq could not complete the request. Check model support and provider status."
            ) from None
        except (
            httpx.HTTPError,
            KeyError,
            ValueError,
            IndexError,
            ValidationError,
            TypeError,
            RecursionError,
            AttributeError,
        ):
            raise ProviderError(
                "The model provider returned an invalid or unavailable response."
            ) from None
