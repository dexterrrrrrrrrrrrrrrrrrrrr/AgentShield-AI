"""Remove only the disposable, credential-free local E2E database."""

import asyncio
import os
import re
import sys

from pymongo import AsyncMongoClient
from pymongo.uri_parser import parse_uri


async def cleanup():
    name = sys.argv[1]
    if not re.fullmatch(r"agentshield_e2e_[a-f0-9]{32}", name):
        raise RuntimeError("Refusing to drop a non-test database")
    uri = os.environ.get("TEST_MONGODB_URI", "mongodb://127.0.0.1:27017")
    parsed = parse_uri(uri)
    if parsed.get("username") or any(
        host not in ("localhost", "127.0.0.1") for host, _ in parsed["nodelist"]
    ):
        raise RuntimeError("Cleanup is restricted to credential-free local MongoDB")
    client = AsyncMongoClient(uri, serverSelectionTimeoutMS=3000)
    try:
        await client.drop_database(name)
    finally:
        await client.close()


asyncio.run(cleanup())
