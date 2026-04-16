from fastapi import APIRouter

from quickquip.app.message_pipeline import rate_limiter

router = APIRouter()

_TOP_USERS_PER_BUCKET = 10


@router.get("/rate-limit")
def get_rate_limit():
    snapshot = rate_limiter.snapshot()
    rules = []
    for name, data in snapshot.items():
        buckets = []
        for bucket in data["buckets"]:
            top_users = sorted(
                bucket["users"].items(),
                key=lambda kv: kv[1],
                reverse=True,
            )[:_TOP_USERS_PER_BUCKET]
            buckets.append({
                "group_id": bucket["group_id"],
                "global_used": bucket["global_used"],
                "active_users": len(bucket["users"]),
                "top_users": [{"user_id": uid, "used": used} for uid, used in top_users],
            })
        rules.append({
            "name": name,
            "scope": data["scope"],
            "global_limit": data["global_limit"],
            "user_limit": data["user_limit"],
            "window_seconds": data["window_seconds"],
            "buckets": buckets,
        })
    rules.sort(key=lambda r: (r["scope"] != "global", r["name"]))
    return {"rules": rules}
