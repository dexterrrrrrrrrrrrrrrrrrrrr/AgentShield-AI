"""Create fresh local Compose credentials once; never overwrite existing secrets."""

import argparse
import os
import secrets
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, default=Path(".env.compose"))
parser.add_argument("--port", type=int, default=3000)
args = parser.parse_args()
if not 1024 <= args.port <= 65535:
    parser.error("Choose a non-privileged local frontend port")
values = {
    "APP_ENV": "development",
    "FRONTEND_PORT": str(args.port),
    "CORS_ORIGINS": f"http://localhost:{args.port}",
    "JWT_SECRET": secrets.token_urlsafe(48),
    "AUDIT_SIGNING_KEY": secrets.token_urlsafe(48),
    "MONGO_ROOT_PASSWORD": secrets.token_urlsafe(36),
    "MONGO_APP_USER": "agentshield_app",
    "MONGO_APP_PASSWORD": secrets.token_urlsafe(36),
    "MONGODB_DATABASE": "agentshield_ai",
    "GROQ_API_KEY": "",
    "GROQ_MODEL": "llama-3.1-8b-instant",
}
try:
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    parser.exit(
        1,
        "Configuration already exists; it was not modified. Use it as-is or edit it securely.\n",
    )
with os.fdopen(descriptor, "w") as output:
    output.write(
        "# Fresh local deployment only. Keep this ignored file and its keys private.\n"
    )
    output.writelines(f"{key}={value}\n" for key, value in values.items())
print(
    f"Created {args.output} with mode 0600. Existing backend/frontend environment files are unchanged."
)
print(
    "Add a free-tier Groq key securely if desired. Sandbox stays disabled in Compose."
)
