from fastapi import APIRouter

from quickquip.app.message_pipeline import rate_limiter

router = APIRouter()


@router.get("/rate-limit")
def get_rate_limit():
    snapshot = rate_limiter.snapshot()
    rules = []
    for name, data in snapshot.items():
        # Rank users by current usage; cap list size so a bursty rule
        # can't produce a multi-MB response during a 5s poll loop.
        top_users = sorted(
            data["users"].items(),
            key=lambda kv: kv[1],
            reverse=True,
        )[:20]
        rules.append({
            "name": name,
            "global_limit": data["global_limit"],
            "user_limit": data["user_limit"],
            "window_seconds": data["window_seconds"],
            "global_used": data["global_used"],
            "active_users": len(data["users"]),
            "top_users": [{"user_id": uid, "used": used} for uid, used in top_users],
        })
    rules.sort(key=lambda r: r["name"])
    return {"rules": rules}
