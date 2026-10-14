"""Cache layer in front of PoliteClient. Cache hits cost no request budget."""
import hashlib
import json
from datetime import timedelta

from django.utils import timezone

from .httpclient import FetchError
from .models import CacheEntry


class Fetcher:
    def __init__(self, client, ttl_seconds=86_400):
        self.client = client
        self.ttl = ttl_seconds
        self.cache_hits = 0
        self.network_requests = 0

    @staticmethod
    def cache_key(url, params):
        canonical = url + "?" + json.dumps(params or {}, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def get_json(self, url, params=None):
        key = self.cache_key(url, params)
        entry = CacheEntry.objects.filter(key=key, expires_at__gt=timezone.now()).first()
        if entry:
            self.cache_hits += 1
            return entry.payload

        raw = self.client.get(url, params)
        self.network_requests += 1
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise FetchError("response was not valid JSON") from exc

        CacheEntry.objects.update_or_create(
            key=key,
            defaults={"payload": data, "expires_at": timezone.now() + timedelta(seconds=self.ttl)},
        )
        return data
