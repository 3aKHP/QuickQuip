from collections import defaultdict, deque
from time import time


class SlidingWindowRateLimiter:
    def __init__(self, global_limit: int, user_limit: int, window_seconds: int = 60):
        self.global_limit = global_limit
        self.user_limit = user_limit
        self.window_seconds = window_seconds
        self.global_timestamps = deque()
        self.user_timestamps = defaultdict(deque)

    def _prune(self, timestamps: deque, now_ts: float) -> None:
        while timestamps and now_ts - timestamps[0] >= self.window_seconds:
            timestamps.popleft()

    def allow(self, user_id: int | str, now_ts: float | None = None) -> bool:
        current_ts = time() if now_ts is None else now_ts

        self._prune(self.global_timestamps, current_ts)
        user_queue = self.user_timestamps[str(user_id)]
        self._prune(user_queue, current_ts)

        if len(self.global_timestamps) >= self.global_limit:
            return False
        if len(user_queue) >= self.user_limit:
            return False

        self.global_timestamps.append(current_ts)
        user_queue.append(current_ts)
        return True

    def snapshot(self, now_ts: float | None = None) -> dict:
        current_ts = time() if now_ts is None else now_ts
        self._prune(self.global_timestamps, current_ts)
        users: dict[str, int] = {}
        empty_keys: list[str] = []
        for user_id, queue in self.user_timestamps.items():
            self._prune(queue, current_ts)
            if queue:
                users[user_id] = len(queue)
            else:
                empty_keys.append(user_id)
        for key in empty_keys:
            del self.user_timestamps[key]
        return {
            "global_limit": self.global_limit,
            "user_limit": self.user_limit,
            "window_seconds": self.window_seconds,
            "global_used": len(self.global_timestamps),
            "users": users,
        }


class KeyedRateLimiter:
    """
    Per-rule rate limiter with optional per-group sub-buckets.

    Each rule config can set scope = "global" or "group" (default "group").
    - scope = "global": one bucket per rule, shared across every group and
      private chat. Use for rules that protect external APIs or shared pools
      (LLM calls, web search, crawler) where the cost is per-caller regardless
      of which chat surface triggered it.
    - scope = "group": one bucket per (rule, group_id), so group A's usage
      doesn't eat into group B's budget. Falls back to the empty bucket key
      when no group_id is supplied (private chat / command handlers with no
      chat context).
    """

    _PRIVATE_BUCKET = ""  # bucket key used when group_id is not applicable

    def __init__(self, rule_limits: dict[str, dict], window_seconds: int = 60):
        self.default_window_seconds = window_seconds
        self.rule_configs: dict[str, dict] = self._build_rule_configs(rule_limits)
        # Key: (rule_name, bucket_key). bucket_key is "" for global or
        # private-chat fallback, otherwise str(group_id).
        self._limiters: dict[tuple[str, str], SlidingWindowRateLimiter] = {}

    def _build_rule_configs(self, rule_limits: dict[str, dict]) -> dict[str, dict]:
        configs: dict[str, dict] = {}
        for name, cfg in rule_limits.items():
            scope = str(cfg.get("scope", "group")).lower()
            if scope not in ("group", "global"):
                scope = "group"
            configs[name] = {
                "global_limit": int(cfg["global_limit"]),
                "user_limit": int(cfg["user_limit"]),
                "scope": scope,
                "window_seconds": int(cfg.get("window", self.default_window_seconds)),
            }
        return configs

    def reload_rules(self, rule_limits: dict[str, dict]) -> None:
        """Replace rule configs; drop limiter buckets for removed or changed rules."""
        new_configs = self._build_rule_configs(rule_limits)
        to_drop: list[tuple[str, str]] = []
        for key in self._limiters:
            rule_name, _ = key
            old_cfg = self.rule_configs.get(rule_name)
            new_cfg = new_configs.get(rule_name)
            if new_cfg is None or old_cfg != new_cfg:
                to_drop.append(key)
        for key in to_drop:
            del self._limiters[key]
        self.rule_configs = new_configs

    def _bucket_key(self, rule_name: str, group_id: int | str | None) -> str:
        cfg = self.rule_configs.get(rule_name)
        if cfg is None or cfg["scope"] == "global" or group_id is None:
            return self._PRIVATE_BUCKET
        return str(group_id)

    def _get_or_create(self, rule_name: str, bucket_key: str) -> SlidingWindowRateLimiter:
        key = (rule_name, bucket_key)
        limiter = self._limiters.get(key)
        if limiter is None:
            cfg = self.rule_configs[rule_name]
            limiter = SlidingWindowRateLimiter(
                global_limit=cfg["global_limit"],
                user_limit=cfg["user_limit"],
                window_seconds=cfg["window_seconds"],
            )
            self._limiters[key] = limiter
        return limiter

    def allow(
        self,
        key: str,
        user_id: int | str,
        now_ts: float | None = None,
        group_id: int | str | None = None,
    ) -> bool:
        if key not in self.rule_configs:
            return True
        bucket_key = self._bucket_key(key, group_id)
        limiter = self._get_or_create(key, bucket_key)
        return limiter.allow(user_id=user_id, now_ts=now_ts)

    def snapshot(self, now_ts: float | None = None) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for name, cfg in self.rule_configs.items():
            result[name] = {
                "scope": cfg["scope"],
                "global_limit": cfg["global_limit"],
                "user_limit": cfg["user_limit"],
                "window_seconds": cfg["window_seconds"],
                "buckets": [],
            }

        to_drop: list[tuple[str, str]] = []
        for (rule_name, bucket_key), limiter in self._limiters.items():
            snap = limiter.snapshot(now_ts)
            if snap["global_used"] == 0 and not snap["users"]:
                to_drop.append((rule_name, bucket_key))
                continue
            if rule_name in result:
                result[rule_name]["buckets"].append({
                    "group_id": bucket_key,
                    "global_used": snap["global_used"],
                    "users": snap["users"],
                })
        for key in to_drop:
            del self._limiters[key]

        for entry in result.values():
            entry["buckets"].sort(key=lambda b: b["group_id"])
        return result
