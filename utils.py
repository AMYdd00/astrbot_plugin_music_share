"""Utility functions for astrbot_plugin_music_share."""

import hashlib
import re
import time
from typing import Optional

# Match Apple Music or Spotify share URLs in message text
MUSIC_URL_RE = re.compile(
    r"https?://"
    r"(?:music\.apple\.com/[a-z]{2,3}/(?:album|song|playlist)/[^/?]+/\d+(?:\?i=\d+)?"
    r"|(?:www\.)?open\.spotify\.com/(?:intl-[a-z]{2,5}/)?(?:track|album)/[a-zA-Z0-9]+"
    r")",
    re.IGNORECASE,
)


def extract_music_url(text: str) -> Optional[str]:
    """Extract the first music share URL from a message text."""
    m = MUSIC_URL_RE.search(text)
    if m:
        return m.group(0)
    return None


def is_group_event(event) -> bool:
    """Check if an event is from a group chat."""
    try:
        event.get_group_id()
        return True
    except (AttributeError, NotImplementedError):
        return False


class ResultCache:
    """Simple in-memory cache with TTL (time-to-live)."""

    def __init__(self, ttl_seconds: int = 600):
        self._cache: dict[str, tuple[object, float]] = {}
        self._ttl = ttl_seconds

    def _key(self, url: str) -> str:
        return hashlib.md5(url.encode()).hexdigest()

    def get(self, url: str) -> Optional[object]:
        key = self._key(url)
        entry = self._cache.get(key)
        if entry is None:
            return None
        value, timestamp = entry
        if time.time() - timestamp > self._ttl:
            del self._cache[key]
            return None
        return value

    def set(self, url: str, value: object) -> None:
        self._cache[self._key(url)] = (value, time.time())