"""Dual-engine music search & download wrapper (yt-dlp + spotdl).

Both engines are queried in parallel for song metadata.  The candidate
whose duration best matches the expected duration (from Apple Music /
Spotify parsing) is selected and downloaded.  If no candidate meets the
configured match_threshold, the download is refused.
"""

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

from rapidfuzz import fuzz as rfuzz

from astrbot.api import logger

from .config import ConfigHelper


@dataclass
class Candidate:
    """A single search result from one of the backends."""

    duration: float  # seconds
    title: str
    source: str  # "yt-dlp" or "spotdl"
    yt_id: str = ""  # YouTube video id (for yt-dlp download)
    cover_url: str = ""


class MusicDownloader:
    """Search YouTube + Spotify for a song and download the best match."""

    def __init__(self, config: ConfigHelper):
        self.config = config

    # ------------------------------------------------------------------#
    #  Public API                                                        #
    # ------------------------------------------------------------------#

    async def search_and_download(
        self,
        title: str,
        artist: str,
        expected_duration: str,
        match_threshold: int,
        download_dir: Path,
    ) -> Optional[Path]:
        """Search, competitively match by duration, and download.

        Parameters
        ----------
        expected_duration : str
            Original song duration, e.g. "3:12" or "0:03:12".
        match_threshold : int
            Percentage (85-100).  99 means the candidate must be within
            ±1 % of the expected duration.
        """
        query = f"{title} {artist}".strip()
        query = re.sub(r'[<>|"&!$`]', "", query).strip()
        if not query:
            logger.warning("[MusicShare] Empty search query")
            return None

        download_dir.mkdir(parents=True, exist_ok=True)

        expected_secs = self._parse_duration(expected_duration)

        # ---- Phase 1: metadata competition ----
        candidates = await self._search_meta(query)
        if not candidates:
            logger.warning(f"[MusicShare] Both engines returned no results for '{query}'")
            return None

        best = self._pick_best(candidates, expected_secs, match_threshold, title)
        if best is None:
            logger.warning(
                f"[MusicShare] No candidate met {match_threshold}% threshold "
                f"for '{query}' (expected {expected_secs}s)"
            )
            return None

        logger.info(
            f"[MusicShare] Selected: {best.title!r} ({best.source}, "
            f"{best.duration}s vs expected {expected_secs}s)"
        )

        # ---- Phase 2: download ----
        filepath = await self._download(best, download_dir)
        return filepath

    # ------------------------------------------------------------------#
    #  Metadata search (parallel)                                        #
    # ------------------------------------------------------------------#

    async def _search_meta(self, query: str) -> List[Candidate]:
        """Run yt-dlp and spotdl in parallel; collect all candidates."""
        results = await asyncio.gather(
            self._ytdlp_search(query),
            self._spotdl_search(query),
            return_exceptions=True,
        )
        candidates: List[Candidate] = []
        for i, r in enumerate(results):
            engine = "yt-dlp" if i == 0 else "spotdl"
            if isinstance(r, Exception):
                logger.warning(f"[MusicShare] {engine} search error: {r}")
            elif r is not None:
                candidates.extend(r)
        return candidates

    async def _ytdlp_search(self, query: str) -> Optional[List[Candidate]]:
        """yt-dlp --dump-json ytsearch3:..."""
        python_exe = self._find_python()
        if not python_exe:
            return None

        cmd = [
            python_exe, "-m", "yt_dlp",
            f"ytsearch3:{query}",
            "--dump-json",
            "--no-warnings",
            "--no-playlist",
            "--skip-download",
            "--quiet",
        ]
        proxy = self.config.proxy()
        if proxy:
            cmd.extend(["--proxy", proxy])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.config.search_timeout(),
            )
            if proc.returncode != 0:
                return None

            candidates: List[Candidate] = []
            for line in stdout.decode("utf-8", errors="replace").strip().split("\n"):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    dur = data.get("duration", 0) or 0
                    yid = data.get("id", "") or ""
                    tit = data.get("title", "")
                    candidates.append(
                        Candidate(
                            duration=float(dur),
                            title=tit,
                            source="yt-dlp",
                            yt_id=yid,
                        )
                    )
                except (json.JSONDecodeError, ValueError):
                    continue
            return candidates or None
        except asyncio.TimeoutError:
            logger.warning("[MusicShare] yt-dlp metadata search timed out")
            return None
        except Exception as e:
            logger.warning(f"[MusicShare] yt-dlp metadata search error: {e}")
            return None

    async def _spotdl_search(self, query: str) -> Optional[List[Candidate]]:
        """spotdl save <query> --save-file -; parse the YAML/JSON output.

        spotdl v4 supports `spotdl save <query>` with --save-file which
        prints the matching song info in JSON lines format.
        """
        python_exe = self._find_python()
        if not python_exe:
            return None

        cmd = [
            python_exe, "-m", "spotdl",
            "save", query,
            "--save-file", "-",
            "--format", self.config.audio_format(),
            "--bitrate", str(self.config.audio_quality()),
        ]
        proxy = self.config.proxy()
        if proxy:
            cmd.extend(["--proxy", proxy])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.config.search_timeout(),
            )
            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                logger.debug(f"[MusicShare] spotdl search failed: {err[:200]}")
                return None

            candidates: List[Candidate] = []
            # spotdl --save-file outputs one JSON object per line (JSONL)
            for line in out.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    dur = data.get("duration", 0) or 0
                    tit = data.get("name", "") or data.get("title", "")
                    yid = data.get("yt_id", "") or data.get("youtube_id", "")
                    candidates.append(
                        Candidate(
                            duration=float(dur),
                            title=tit,
                            source="spotdl",
                            yt_id=yid,
                        )
                    )
                except (json.JSONDecodeError, ValueError):
                    continue
            return candidates or None
        except asyncio.TimeoutError:
            logger.warning("[MusicShare] spotdl metadata search timed out")
            return None
        except Exception as e:
            logger.warning(f"[MusicShare] spotdl metadata search error: {e}")
            return None

    # ------------------------------------------------------------------#
    #  Duration matching                                                 #
    # ------------------------------------------------------------------#

    @staticmethod
    def _parse_duration(dur: str) -> float:
        """Parse a duration string into seconds.

        Accepted formats: "3:12", "0:03:12", "192", "3.2"
        """
        if not dur:
            return 0.0
        dur = dur.strip()
        # Already a plain number (seconds)
        try:
            return float(dur)
        except ValueError:
            pass
        # H:MM:SS or M:SS
        parts = dur.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return 0.0

    # Words that strongly suggest a non-original version
    _NEGATIVE_KEYWORDS = re.compile(
        r"\b(instrumental|karaoke|piano|cover|remix|tribute|acoustic|"
        r"live|orchestral|backing\s*track|concert|unplugged|mix|edit|"
        r"orchestra|quartet|trio|band\s*version|rehearsal|demo|nightcore|"
        r"slowed|sped\s*up|vocal\s*only|off\s*vocal|minus\s*one)\b",
        re.IGNORECASE,
    )

    @classmethod
    def _pick_best(
        cls,
        candidates: List[Candidate],
        expected_secs: float,
        threshold_pct: int,
        original_title: str,
    ) -> Optional[Candidate]:
        """Return the candidate that best matches the original song.

        Scoring (weighted sum):
          - Duration match     40%
          - Title similarity   40%
          - Source bonus       20%  (spotdl > yt-dlp)
          - Negative keyword penalty  -50% if matched

        If no expected duration is available (0.0), returns the
        highest-scored candidate without filtering.
        """
        if not candidates:
            return None

        has_duration = expected_secs > 0
        max_deviation = (100 - threshold_pct) / 100.0  # e.g. 0.01 for 99%

        clean_orig = original_title.lower().strip()

        best: Optional[Candidate] = None
        best_score = -999.0

        for cand in candidates:
            # 1. Duration score (0..1)
            if has_duration:
                deviation = abs(cand.duration - expected_secs) / expected_secs
                if deviation > max_deviation:
                    continue  # hard filter
                dur_score = 1.0 - deviation
            else:
                dur_score = 0.5  # neutral when no expected duration

            # 2. Title similarity score (0..1)
            cand_title = cand.title.lower().strip()
            title_score = rfuzz.partial_ratio(clean_orig, cand_title) / 100.0

            # 3. Source bonus
            source_score = 0.8 if cand.source == "spotdl" else 0.2

            # 4. Negative keyword penalty
            neg_penalty = 0.0
            if not cls._NEGATIVE_KEYWORDS.search(clean_orig):
                # Only penalize if the original title does NOT contain
                # these keywords (e.g. "remix" in the actual song name is fine)
                if cls._NEGATIVE_KEYWORDS.search(cand_title):
                    neg_penalty = 0.5

            total = (
                0.4 * dur_score
                + 0.4 * title_score
                + 0.2 * source_score
                - neg_penalty
            )

            if total > best_score:
                best_score = total
                best = cand

        return best

    # ------------------------------------------------------------------#
    #  Download logic                                                    #
    # ------------------------------------------------------------------#

    async def _download(self, cand: Candidate, download_dir: Path) -> Optional[Path]:
        """Download the audio for a single candidate."""
        output_template = str(download_dir / "%(title)s.%(ext)s")
        python_exe = self._find_python()
        if not python_exe:
            return None

        if cand.source == "spotdl" and cand.yt_id:
            # spotdl can download via yt_id directly
            query = f"https://music.youtube.com/watch?v={cand.yt_id}"
        elif cand.source == "yt-dlp" and cand.yt_id:
            query = f"https://www.youtube.com/watch?v={cand.yt_id}"
        else:
            logger.warning(f"[MusicShare] No yt_id for candidate {cand.title!r}")
            return None

        cmd = [
            python_exe, "-m", "yt_dlp",
            query,
            "--no-playlist",
            "--no-warnings",
            "--extract-audio",
            f"--audio-format={self.config.audio_format()}",
            f"--audio-quality={self.config.audio_quality()}",
            "--max-filesize", f"{self.config.max_file_size_mb()}M",
            "--output", output_template,
            "--no-progress",
            "--print", "after_move:filepath",
        ]
        proxy = self.config.proxy()
        if proxy:
            cmd.extend(["--proxy", proxy])

        try:
            logger.info(f"[MusicShare] Downloading: {cand.title!r} via {query}")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.config.search_timeout() * 2,
            )
            if proc.returncode != 0:
                err = stderr.decode("utf-8", errors="replace")[:200]
                logger.warning(f"[MusicShare] Download failed: {err}")
                return None

            stdout_text = stdout.decode("utf-8", errors="replace").strip()
            if stdout_text:
                filepath = Path(stdout_text.split("\n")[-1].strip())
                if filepath.exists():
                    logger.info(f"[MusicShare] Downloaded: {filepath}")
                    return filepath

            # Fallback: scan download_dir
            audio_files = sorted(
                download_dir.glob(f"*.{self.config.audio_format()}"),
                key=os.path.getmtime,
                reverse=True,
            )
            if audio_files:
                return audio_files[0]

            return None
        except asyncio.TimeoutError:
            logger.warning("[MusicShare] Download timed out")
            return None
        except Exception as e:
            logger.error(f"[MusicShare] Download error: {e}")
            return None

    # ------------------------------------------------------------------#
    #  Helpers                                                           #
    # ------------------------------------------------------------------#

    @staticmethod
    def _find_python() -> Optional[str]:
        """Return the python executable path."""
        import sys
        try:
            return sys.executable
        except Exception:
            return None

    @staticmethod
    def clean_file(filepath: Path) -> None:
        """Remove a downloaded temporary file."""
        try:
            if filepath.exists():
                filepath.unlink()
                logger.debug(f"[MusicShare] Cleaned up: {filepath}")
        except Exception as e:
            logger.warning(f"[MusicShare] Failed to clean {filepath}: {e}")