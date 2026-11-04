"""One small async pool per application process; no Motor dependency."""

from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from .config import Settings

# Reserved names only: no Phase 3 models, operations, or indexes yet.
FUTURE_COLLECTIONS = ("agent_configs", "execution_logs")


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
        return client, db
    except PyMongoError:
        if client is not None:
            await client.close()
        raise RuntimeError(
            "MongoDB startup verification failed; check connection and indexes"
        ) from None
