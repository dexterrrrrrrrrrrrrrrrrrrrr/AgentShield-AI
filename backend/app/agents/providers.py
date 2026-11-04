"""Provider errors are mapped without leaking response bodies or credentials."""

import json

import groq
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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


class Providers:
    def __init__(self, settings):
        self.settings = settings

    async def complete(
        self, provider: str, model: str, messages: list[dict], allowed: list[str]
    ) -> Reply:
        s = self.settings
        try:
            if provider == "groq":
                if not s.groq_api_key.get_secret_value():
                    raise ProviderError(
                        "Groq is not configured. Set GROQ_API_KEY on the backend.", 503
                    )
                async with groq.AsyncGroq(
                    api_key=s.groq_api_key.get_secret_value(),
                    timeout=s.agent_provider_timeout,
                    max_retries=0,
                ) as client:
                    # Explicit availability check; no silent model or provider fallback.
                    await client.models.retrieve(model)
                    result = await client.chat.completions.create(
                        model=model,
                        messages=messages,
                        tools=definitions(allowed) or None,
                        max_completion_tokens=1024,
                        temperature=0.2,
                    )
                    message = result.choices[0].message
                    return Reply(
                        content=message.content or "",
                        calls=[
                            ToolRequest(
                                name=c.function.name,
                                arguments=json.loads(c.function.arguments),
                            )
                            for c in message.tool_calls or []
                        ],
                    )
            if not s.ollama_enabled:
                raise ProviderError(
                    "Ollama is disabled. Enable it explicitly to use a local model.",
                    503,
                )
            # URL is operator-configured and restricted to loopback; never supplied by users/models.
            async with httpx.AsyncClient(
                base_url=s.ollama_url, timeout=s.agent_provider_timeout, trust_env=False
            ) as client:
                tags = await client.get("/api/tags")
                tags.raise_for_status()
                if model not in [m["name"] for m in tags.json().get("models", [])]:
                    raise ProviderError(
                        "The selected Ollama model is not installed. No model was downloaded.",
                        422,
                    )
                result = await client.post(
                    "/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "tools": definitions(allowed),
                        "stream": False,
                        "keep_alive": "1m",
                        "options": {"num_ctx": 4096, "num_predict": 1024},
                    },
                )
                result.raise_for_status()
                if len(result.content) > 100000:
                    raise ProviderError("Provider response exceeded the size limit")
                message = result.json()["message"]
                return Reply(
                    content=message.get("content", ""),
                    calls=[
                        ToolRequest(
                            name=c["function"]["name"],
                            arguments=c["function"]["arguments"],
                        )
                        for c in message.get("tool_calls", [])
                    ],
                )
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
        ):
            raise ProviderError(
                "The model provider returned an invalid or unavailable response."
            ) from None
