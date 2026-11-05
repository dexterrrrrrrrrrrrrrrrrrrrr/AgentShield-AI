"""Atomic, short-lived MongoDB connection admission across API workers."""

from datetime import timedelta

from pymongo import ReturnDocument

from ..security import utcnow


class ConnectionLeases:
    def __init__(self, db):
        self.collection = db.monitor_connections

    async def acquire(self, uid, cid):
        now = utcnow()
        await self.collection.update_one(
            {"_id": "pool"}, {"$setOnInsert": {"slots": []}}, upsert=True
        )
        live = {
            "$filter": {
                "input": "$slots",
                "as": "s",
                "cond": {"$gt": ["$$s.until", now]},
            }
        }
        owned = {
            "$filter": {"input": live, "as": "s", "cond": {"$eq": ["$$s.uid", uid]}}
        }
        return bool(
            await self.collection.find_one_and_update(
                {
                    "_id": "pool",
                    "$expr": {
                        "$and": [
                            {"$lt": [{"$size": live}, 20]},
                            {"$lt": [{"$size": owned}, 4]},
                        ]
                    },
                },
                [
                    {
                        "$set": {
                            "slots": {
                                "$concatArrays": [
                                    live,
                                    [
                                        {
                                            "id": cid,
                                            "uid": uid,
                                            "until": now + timedelta(seconds=60),
                                        }
                                    ],
                                ]
                            }
                        }
                    }
                ],
                return_document=ReturnDocument.AFTER,
            )
        )

    async def renew(self, uid, cid):
        now = utcnow()
        result = await self.collection.update_one(
            {
                "_id": "pool",
                "slots": {"$elemMatch": {"id": cid, "uid": uid, "until": {"$gt": now}}},
            },
            {"$set": {"slots.$.until": now + timedelta(seconds=60)}},
        )
        return bool(result.matched_count)

    async def release(self, uid, cid):
        await self.collection.update_one(
            {"_id": "pool"}, {"$pull": {"slots": {"id": cid, "uid": uid}}}
        )
