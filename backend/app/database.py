"""One small async pool per application process; no Motor dependency."""

from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from .config import Settings

# Phase 4 execution logging remains reserved; no sandbox operations exist.
FUTURE_COLLECTIONS = ("execution_logs",)


async def connect_database(settings: Settings):
    client = None
    try:
        client = AsyncMongoClient(
            settings.mongodb_uri.get_secret_value(),
            maxPoolSize=settings.mongodb_max_pool_size,
            minPoolSize=0,
            maxIdleTimeMS=30000,
            waitQueueTimeoutMS=2000,
            serverSelectionTimeoutMS=settings.mongodb_timeout_ms,
            connectTimeoutMS=settings.mongodb_timeout_ms,
            socketTimeoutMS=5000,
            tz_aware=True,
        )
        await client.admin.command("ping")
        db = client[settings.mongodb_database]
        await db.users.create_index("email", unique=True, name="unique_email")
        await db.sessions.create_index(
            "expires_at", expireAfterSeconds=0, name="session_expiry"
        )
        await db.sessions.create_index("user_id", name="session_owner")
        await db.security_events.create_index(
            "expires_at", expireAfterSeconds=0, name="rate_expiry"
        )
        await db.agent_sessions.create_index(
            [("user_id", 1), ("created_at", -1), ("_id", -1)]
        )
        await db.agent_messages.create_index(
            [("user_id", 1), ("session_id", 1), ("turn", 1)], unique=True
        )
        await db.agent_configs.create_index("user_id", unique=True)
        return client, db
    except PyMongoError:
        if client is not None:
            await client.close()
        raise RuntimeError(
            "MongoDB startup verification failed; check connection and indexes"
        ) from None
