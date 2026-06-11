"""Apple Music share link parser.

Extracts song metadata from Apple Music web pages by parsing HTML,
without relying on any API tokens.  Supports all regional storefronts
(cn, us, jp, etc.) because the <title> tag always contains readable
song/artist text.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup


@dataclass
class SongInfo:
    title: str
    artist: str
    album: str = ""
    cover_url: str = ""
    source: str = "apple_music"
    duration: str = ""
    release_date: str = ""


AM_URL_RE = re.compile(
    r"https?://music\.apple\.com/[a-z]{2,3}/"
    r"(?:album|song|playlist)/"
    r"[^/?]+/(\d+)"
    r"(?:\?i=(\d+))?",
    re.IGNORECASE,
)

TITLE_PATTERNS = [
    re.compile(r"^(.+?)\s+by\s+(.+?)\s+on\s+Apple\s+Music\s*$", re.IGNORECASE),
    re.compile(r"^(.+?)\s*-\s*(.+?)\s+on\s+Apple\s+Music\s*$", re.IGNORECASE),
    re.compile(r"^(.+?)\s*[—–]\s*(.+?)\s+on\s+Apple\s+Music\s*$", re.IGNORECASE),
]


class AppleMusicParser:
    """Parse Apple Music share links to extract song/artist metadata."""

    def __init__(self, proxy: Optional[str] = None):
        self.proxy = proxy

    @staticmethod
    def is_apple_music_url(url: str) -> bool:
        return bool(AM_URL_RE.search(url))

    async def parse(self, url: str) -> Optional[SongInfo]:
        if not self.is_apple_music_url(url):
            return None

        html = await self._fetch(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")

        title = None
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            title = title_tag.string.strip()

        if not title:
            return None

        song_name, artist = self._parse_title(title)
        if not song_name:
            return None

        cover_url = self._extract_cover(soup)
        album = self._extract_album(soup)
        duration, release_date = self._extract_jsonld(soup)

        return SongInfo(
            title=song_name,
            artist=artist or "",
            album=album,
            cover_url=cover_url,
            duration=duration,
            release_date=release_date,
        )

    _BIDI_RE = re.compile(r"[\u200e\u200f\u202a-\u202e\u00a0]")

    def _parse_title(self, title: str) -> tuple[Optional[str], Optional[str]]:
        title = self._BIDI_RE.sub(" ", title).strip()

        for pattern in TITLE_PATTERNS:
            m = pattern.match(title)
            if m:
                song = m.group(1).strip()
                artist = m.group(2).strip()
                artist = self._clean_artist(artist)
                return song, artist

        cleaned = re.sub(
            r"\s*(?:on\s+)?Apple\s+Music\s*$", "", title, flags=re.IGNORECASE
        ).strip()

        for sep in (" - ", " – ", " — "):
            if sep in cleaned:
                parts = cleaned.split(sep, 1)
                artist = self._clean_artist(parts[1].strip())
                return parts[0].strip(), artist

        return cleaned, None

    @staticmethod
    def _clean_artist(artist: str) -> str:
        artist = re.sub(r"\s*[-—–]\s*$", "", artist).strip()
        m = re.match(r"^由\s*(.+?)\s*演唱\s*$", artist)
        if m:
            return m.group(1).strip()
        m = re.match(r"^(.+?)\s*演唱\s*$", artist)
        if m:
            return m.group(1).strip()
        m = re.match(r"^由\s*(.+?)\s*$", artist)
        if m:
            return m.group(1).strip()
        return artist

    _COVER_SIZE_RE = re.compile(r"/\d+x\d+(?:bb|wp|bf)(?:-\d+)?(?:\.\w+)?$")

    def _extract_cover(self, soup: BeautifulSoup) -> str:
        tw = soup.find("meta", attrs={"name": "twitter:image"})
        if tw and tw.get("content"):
            src = tw["content"]
            if isinstance(src, str):
                return self._normalize_cover_url(src)
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            src = og["content"]
            if isinstance(src, str):
                return self._normalize_cover_url(src)
        return ""

    @classmethod
    def _normalize_cover_url(cls, url: str) -> str:
        return cls._COVER_SIZE_RE.sub("/1200x1200bb.jpg", url)

    @staticmethod
    def _extract_jsonld(soup: BeautifulSoup) -> tuple[str, str]:
        """Extract duration and release_date from JSON-LD script blocks."""
        duration = ""
        release_date = ""

        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if not isinstance(data, dict):
                    continue

                # Extract duration
                raw_dur = data.get("timeRequired", "")
                if not raw_dur:
                    raw_dur = data.get("duration", "")
                if raw_dur:
                    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", raw_dur)
                    if m:
                        h = m.group(1) or "0"
                        mi = m.group(2) or "00"
                        s = m.group(3) or "00"
                        duration = f"{h}:{mi.zfill(2)}:{s.zfill(2)}"
                        # Strip leading 0:
                        duration = re.sub(r"^0:", "", duration)
                        duration = re.sub(r"^00:", "", duration)

                # Extract release_date
                rdate = data.get("datePublished", "")
                if rdate:
                    release_date = rdate[:10]  # YYYY-MM-DD
            except Exception:
                pass

        return duration, release_date

    def _extract_album(self, soup: BeautifulSoup) -> str:
        """Extract album name from meta tags or JSON-LD, filtering out URLs."""
        # 1) Try music:album meta tag (property or name)
        for attrs in ({"property": "music:album"}, {"name": "music:album"}):
            meta = soup.find("meta", attrs=attrs)
            if meta and meta.get("content"):
                val = str(meta["content"]).strip()
                if val and not val.startswith("http"):
                    return val

        # 2) Try JSON-LD: look for MusicAlbum -> name
        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    album_name = self._find_album_in_jsonld(data)
                    if album_name:
                        return album_name
            except Exception:
                pass

        # 3) Try og:title as last resort (some pages embed album there)
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            val = str(og_title["content"]).strip()
            if val and not val.startswith("http"):
                return val

        return ""

    @staticmethod
    def _find_album_in_jsonld(data: dict, depth: int = 0) -> str:
        """Recursively search JSON-LD for an album name."""
        if depth > 3:
            return ""
        if data.get("@type") in ("MusicAlbum", "Album") and data.get("name"):
            return str(data["name"]).strip()
        # Check inAlbum / album references
        for key in ("inAlbum", "album", "itemListElement", "@graph"):
            val = data.get(key)
            if isinstance(val, dict):
                result = AppleMusicParser._find_album_in_jsonld(val, depth + 1)
                if result:
                    return result
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        result = AppleMusicParser._find_album_in_jsonld(item, depth + 1)
                        if result:
                            return result
        # Walk all nested dicts
        for key, val in data.items():
            if isinstance(val, dict):
                result = AppleMusicParser._find_album_in_jsonld(val, depth + 1)
                if result:
                    return result
        return ""

    async def _fetch(self, url: str) -> Optional[str]:
        kwargs = {}
        if self.proxy:
            kwargs["proxy"] = self.proxy
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=15),
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    },
                    **kwargs,
                ) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.text()
        except Exception:
            return None