"""Small, deterministic boundaries for untrusted JSON and credential-bearing text."""

import json
import math
import re
from urllib.parse import unquote, urlsplit


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("Non-finite JSON number")

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 32:
            raise ValueError("JSON nesting limit")
        if isinstance(item, dict):
            pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            pending.extend((v, depth + 1) for v in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Non-finite JSON number")
    return value


def credential_values(settings):
    uri = settings.mongodb_uri.get_secret_value()
    values = [
        settings.jwt_secret.get_secret_value(),
        settings.groq_api_key.get_secret_value(),
        settings.google_client_secret.get_secret_value(),
        settings.audit_signing_key.get_secret_value(),
        uri,
    ]
    try:
        password = urlsplit(uri).password
        if password:
            values.extend((password, unquote(password)))
    except ValueError:
        pass
    return [v for v in values if v]


CREDENTIAL = re.compile(
    r"(?i)(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    r"|(?:gsk_|ghp_|github_pat_)[\w-]+"
    r"|eyJ[\w-]+\.[\w-]+\.[\w-]+"
    r"|Bearer\s+[\w.\-]+"
    r"|(?:mongodb(?:\+srv)?|https?)://[^\s/@:]+:[^\s/@]+@[^\s]+"
    r'|["\x27]?(?:api[_ -]?key|password|secret|access[_ -]?token|refresh[_ -]?token)["\x27]?\s*[:=]\s*["\x27]?[^\s,;"\x27}]+)'
)


def redact(text, secrets):
    for secret in sorted(filter(None, secrets), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return CREDENTIAL.sub("[REDACTED]", text)[:12000]


def redact_data(value, secrets):
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, dict):
        return {k: redact_data(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_data(v, secrets) for v in value]
    return value


def allowed_origin(connection):
    headers = connection.headers
    origins = (
        headers.getlist("origin")
        if hasattr(headers, "getlist")
        else [headers.get("origin")]
    )
    return len(origins) == 1 and origins[0] in connection.app.state.settings.origins
