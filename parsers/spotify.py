"""Spotify share link parser.

Extracts song metadata from open.spotify.com web pages by parsing
HTML meta tags (og:title, og:description) and JSON-LD data.  No API keys needed.
"""

import asyncio
import json
import re
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup

from astrbot.api import logger

from .apple_music import SongInfo

# Spotify track share links:
#   open.spotify.com/track/{id}
#   open.spotify.com/intl-{lang}/track/{id}
SPOTIFY_TRACK_RE = re.compile(
    r"https?://(?:www\.)?open\.spotify\.com/(?:intl-[a-z]{2,5}/)?track/([a-zA-Z0-9]+)",
    re.IGNORECASE,
)

# Spotify album links (we can extract info too):
#   open.spotify.com/album/{id}
SPOTIFY_ALBUM_RE = re.compile(
    r"https?://(?:www\.)?open\.spotify\.com/(?:intl-[a-z]{2,5}/)?album/([a-zA-Z0-9]+)",
    re.IGNORECASE,
)

# Alternative: extract song via oEmbed endpoint (no HTML parsing needed)
SPOTIFY_OEMBED_URL = "https://open.spotify.com/oembed?url={url}"


class SpotifyParser:
    """Parse Spotify share links to extract song/artist metadata."""

    def __init__(self, proxy: Optional[str] = None):
        self.proxy = proxy

    @staticmethod
    def is_spotify_url(url: str) -> bool:
        """Check if the url is a Spotify track or album link."""
        clean = url.split("?")[0] if "?" in url else url
        return bool(SPOTIFY_TRACK_RE.search(clean) or SPOTIFY_ALBUM_RE.search(clean))

    async def parse(self, url: str) -> Optional[SongInfo]:
        """Fetch the Spotify page and extract song info.

        Uses oEmbed for title/cover, supplements with HTML for
        artist, album, duration and release_date."""
        # oEmbed gives title + cover reliably (no JS needed)
        info = await self._parse_via_oembed(url)
        if not info:
            # Fallback: HTML meta tag parsing
            info = await self._parse_via_html(url)

        if not info:
            return None

        # Supplement extra metadata from HTML (best-effort)
        html = await self._fetch(url)
        if html:
            soup = BeautifulSoup(html, "html.parser")
            extra = self._parse_html_extra(soup)
            if not info.artist and extra.get("artist"):
                info.artist = extra["artist"]
            if not info.album and extra.get("album"):
                info.album = extra["album"]
            if not info.duration and extra.get("duration"):
                info.duration = extra["duration"]
            if not info.release_date and extra.get("release_date"):
                info.release_date = extra["release_date"]

        return info

    async def _parse_via_oembed(self, url: str) -> Optional[SongInfo]:
        """Parse via Spotify oEmbed endpoint, with retry."""
        oembed_url = SPOTIFY_OEMBED_URL.format(url=url)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession() as session:
                    kwargs = {"headers": headers, "timeout": aiohttp.ClientTimeout(total=15)}
                    if self.proxy:
                        kwargs["proxy"] = self.proxy
                    async with session.get(oembed_url, **kwargs) as resp:
                        if resp.status != 200:
                            if attempt < 2:
                                await asyncio.sleep(1)
                                continue
                            return None
                        data = await resp.json()
                        title = data.get("title", "")
                        if not title:
                            return None
                        # title format: "Song Name by Artist"
                        song_name, artist = self._split_oembed_title(title)
                        cover_url = data.get("thumbnail_url", "")
                        return SongInfo(
                            title=song_name or title,
                            artist=artist or "",
                            cover_url=cover_url,
                            source="spotify",
                        )
            except Exception as e:
                logger.debug(f"[MusicShare] Spotify oEmbed attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(1)
                else:
                    return None
        return None

    @staticmethod
    def _split_oembed_title(title: str) -> tuple[Optional[str], Optional[str]]:
        """Split title into song name and artist."""
        # "Song by Artist"
        m = re.match(r"^(.+?)\s+by\s+(.+?)$", title, re.IGNORECASE)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        # "Song - Artist"
        for sep in (" - ", " – ", " — "):
            if sep in title:
                parts = title.split(sep, 1)
                return parts[0].strip(), parts[1].strip()
        # "Song (feat. Artist)" / "Song (ft. Artist)"
        m = re.match(
            r"^(.+?)\s*\(f(?:ea)?t\.?\s+(.+?)\)\s*$", title, re.IGNORECASE
        )
        if m:
            song = m.group(1).strip()
            artist = m.group(2).strip()
            # Remove trailing ")" cleanup
            artist = artist.rstrip(")")
            return song, artist
        # "Song feat. Artist" (without parentheses)
        m = re.match(
            r"^(.+?)\s+f(?:ea)?t\.?\s+(.+?)$", title, re.IGNORECASE
        )
        if m:
            return m.group(1).strip(), m.group(2).strip()
        # Can't split — just return title as is
        return title.strip(), None

    async def _parse_via_html(self, url: str) -> Optional[SongInfo]:
        """Fallback: parse via HTML meta tags."""
        html = await self._fetch(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")

        og_title = soup.find("meta", property="og:title")
        title_text = str(og_title["content"]).strip() if og_title and og_title.get("content") else ""
        og_desc = soup.find("meta", property="og:description")
        desc_text = str(og_desc["content"]).strip() if og_desc and og_desc.get("content") else ""

        if not title_text and not desc_text:
            return None

        song_name, artist = self._parse_info(title_text, desc_text)
        cover_url = ""
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            cover_url = str(og_image["content"])

        return SongInfo(
            title=song_name or title_text,
            artist=artist or "",
            cover_url=cover_url,
            source="spotify",
        )

    def _parse_info(
        self, og_title: str, og_desc: str
    ) -> tuple[Optional[str], Optional[str]]:
        """Extract song name and artist from meta tag contents."""
        song_name = None
        artist = None

        if og_desc:
            parts = [p.strip() for p in og_desc.split("·")]
            if len(parts) >= 2:
                song_name = parts[0] if parts[0] else None
                for p in parts[1:]:
                    if p and not re.match(r"^\d{4}$", p):
                        artist = p
                        break

        if (not song_name or not artist) and og_title:
            by_match = re.match(r"^(.+?)\s+by\s+(.+?)$", og_title, re.IGNORECASE)
            if by_match:
                if not song_name:
                    song_name = by_match.group(1).strip()
                if not artist:
                    artist = by_match.group(2).strip()
            if not song_name:
                song_name = og_title

        return song_name, artist

    def _parse_html_extra(self, soup: BeautifulSoup) -> dict:
        """Extract album, duration, release_date and extra artist from HTML/JSON-LD."""
        result: dict = {}

        # --- album ---
        # 1) music:album meta
        album_meta = soup.find("meta", attrs={"name": "music:album"})
        if album_meta and album_meta.get("content"):
            val = str(album_meta["content"]).strip()
            if val and not val.startswith("http"):
                result["album"] = val

        # 2) og:description sometimes contains album info after "·"
        if not result.get("album"):
            og_desc = soup.find("meta", property="og:description")
            if og_desc and og_desc.get("content"):
                desc = str(og_desc["content"])
                parts = [p.strip() for p in desc.split("·")]
                # Format: "Song · Artist · Album · year"
                if len(parts) >= 3:
                    third = parts[2]
                    if third and not re.match(r"^\d{4}$", third):
                        result["album"] = third

                # artist from desc if missing (for supplement)
                if len(parts) >= 2:
                    second = parts[1]
                    if second and not re.match(r"^\d{4}$", second):
                        result["artist"] = second

        # 3) JSON-LD
        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    self._walk_jsonld_extra(data, result)
            except Exception:
                pass

        # --- release_date from meta ---
        if not result.get("release_date"):
            release_meta = soup.find("meta", attrs={"name": "music:release_date"})
            if release_meta and release_meta.get("content"):
                val = str(release_meta["content"]).strip()
                if val:
                    result["release_date"] = val[:10]

        return result

    @staticmethod
    def _walk_jsonld_extra(data: dict, result: dict, depth: int = 0):
        """Recursively walk JSON-LD for album, duration, release_date."""
        if depth > 3:
            return

        # Album from MusicAlbum
        if data.get("@type") in ("MusicAlbum", "Album") and data.get("name"):
            if not result.get("album"):
                result["album"] = str(data["name"]).strip()

        # Release date
        if not result.get("release_date"):
            rdate = data.get("datePublished", "")
            if rdate:
                result["release_date"] = str(rdate)[:10]

        # Duration
        if not result.get("duration"):
            raw_dur = data.get("timeRequired", "") or data.get("duration", "")
            if raw_dur:
                m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", str(raw_dur))
                if m:
                    h = m.group(1) or "0"
                    mi = m.group(2) or "00"
                    s = m.group(3) or "00"
                    dur_str = f"{h}:{mi.zfill(2)}:{s.zfill(2)}"
                    dur_str = re.sub(r"^0:", "", dur_str)
                    dur_str = re.sub(r"^00:", "", dur_str)
                    result["duration"] = dur_str

        # Walk nested
        for key in ("inAlbum", "album", "itemListElement", "@graph", "track", "byArtist"):
            val = data.get(key)
            if isinstance(val, dict):
                SpotifyParser._walk_jsonld_extra(val, result, depth + 1)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        SpotifyParser._walk_jsonld_extra(item, result, depth + 1)

        # Also check for albumOf type
        for key, val in data.items():
            if isinstance(val, dict) and val.get("@type") in ("MusicAlbum", "Album"):
                if not result.get("album") and val.get("name"):
                    result["album"] = str(val["name"]).strip()

    async def _fetch(self, url: str) -> Optional[str]:
        """Fetch HTML content from the URL."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        try:
            async with aiohttp.ClientSession() as session:
                kwargs = {"headers": headers, "timeout": aiohttp.ClientTimeout(total=15)}
                if self.proxy:
                    kwargs["proxy"] = self.proxy
                async with session.get(url, **kwargs) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.text()
        except Exception:
            return None