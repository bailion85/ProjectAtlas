from __future__ import annotations

import os
from typing import Any

from core.providers.market_provider import ProviderError


X_PROVIDER_VERSION = 1


class XFeedProvider:
    name = "X API v2"
    base_url = "https://api.x.com/2"

    def __init__(self, cache, bearer_token: str | None = None, timeout: int = 20):
        self.cache = cache
        self.bearer_token = (bearer_token or os.getenv("X_BEARER_TOKEN", "")).strip()
        self.timeout = timeout
        self.daily_limit = max(1, int(os.getenv("X_DAILY_REQUEST_LIMIT", "20")))
        self.max_posts = max(5, min(100, int(os.getenv("X_POSTS_PER_SOURCE", "10"))))

    @property
    def configured(self) -> bool:
        return bool(self.bearer_token)

    def recent_posts(self, username: str) -> dict[str, Any]:
        handle = username.strip().lstrip("@").lower()
        if not handle:
            raise ProviderError("An X handle is required.")
        cached = self.cache.get("x_feed", "recent_posts", {"handle": handle})
        if cached:
            return {**cached.value, "cache_status": "Fresh cache", "cache_age_seconds": cached.age_seconds}
        if not self.configured:
            raise ProviderError("X_BEARER_TOKEN is not configured.")
        user = self._get(f"/users/by/username/{handle}", {"user.fields": "username,name"})
        user_data = user.get("data") or {}
        user_id = str(user_data.get("id", ""))
        if not user_id:
            raise ProviderError(f"X account @{handle} was not found.")
        timeline = self._get(f"/users/{user_id}/tweets", {
            "max_results": str(self.max_posts), "exclude": "replies,retweets",
            "tweet.fields": "created_at,entities,lang,public_metrics",
        })
        value = {
            "handle": str(user_data.get("username") or handle),
            "name": str(user_data.get("name") or handle),
            "posts": list(timeline.get("data") or []), "cache_status": "Live X API",
        }
        self.cache.put("x_feed", "recent_posts", {"handle": handle}, value, 3600)
        return value

    def usage_status(self) -> dict[str, Any]:
        return self.cache.usage_status("x_api", self.daily_limit)

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        try:
            import requests
        except ModuleNotFoundError as exc:
            raise ProviderError("Install requests to use X feed sync.") from exc
        if not self.cache.claim_request("x_api", self.daily_limit):
            status = self.usage_status()
            raise ProviderError(
                f"Atlas reached its X request limit ({status['used']}/{status['usable_limit']}) for today."
            )
        try:
            response = requests.get(
                self.base_url + path, params=params,
                headers={"Authorization": f"Bearer {self.bearer_token}"}, timeout=self.timeout,
            )
            payload = response.json()
        except requests.RequestException as exc:
            raise ProviderError(f"X request failed: {exc}") from exc
        except ValueError as exc:
            raise ProviderError("X returned an invalid response.") from exc
        if response.status_code >= 400 or payload.get("errors"):
            detail = payload.get("detail") or payload.get("title")
            if not detail and payload.get("errors"):
                detail = "; ".join(str(item.get("detail") or item.get("title")) for item in payload["errors"])
            raise ProviderError(f"X API: {detail or f'HTTP {response.status_code}'}")
        return payload
