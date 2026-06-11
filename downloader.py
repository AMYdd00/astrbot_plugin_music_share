"""YouTube search & download wrapper using yt-dlp.

Uses yt-dlp to search for a song on YouTube and download the best
matching audio file.  Runs yt-dlp as a subprocess to avoid blocking
and to leverage its mature search/extraction logic.
"""

import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Optional

from astrbot.api import logger

from .config import ConfigHelper


class MusicDownloader:
    """Search YouTube for a song and download audio via yt-dlp."""

    def __init__(self, config: ConfigHelper):
        self.config = config
        self.yt_dlp_path = self._find_ytdlp()

    @staticmethod
    def _find_ytdlp() -> str:
        """Locate the yt-dlp executable.  Prefer the module entry point."""
        # Check if yt-dlp is available as a Python module
        ytdlp_module = shutil.which("yt-dlp")
        if ytdlp_module:
            return "yt-dlp"

        # Try python -m yt_dlp
        return "python -m yt_dlp"

    async def search_and_download(
        self, title: str, artist: str, download_dir: Path
    ) -> Optional[Path]:
        """Search YouTube for title+artist and download the best audio.

        Returns the path to the downloaded audio file, or None on failure.
        """
        query = f"{title} {artist}".strip()
        # Sanitize query: remove special chars that might confuse shell
        query = re.sub(r'[<>|"&!$`]', "", query)
        query = query.strip()

        if not query:
            logger.warning("[MusicShare] Empty search query")
            return None

        download_dir.mkdir(parents=True, exist_ok=True)

        # yt-dlp output template
        output_template = str(download_dir / "%(title)s.%(ext)s")

        # Build yt-dlp command
        cmd = [
            self.yt_dlp_path,
            f"ytsearch1:{query}",  # search YouTube, take first result
            "--no-playlist",
            "--no-warnings",
            "--extract-audio",
            f"--audio-format={self.config.audio_format()}",
            f"--audio-quality={self.config.audio_quality()}",
            "--max-filesize",
            f"{self.config.max_file_size_mb()}M",
            "--output",
            output_template,
            "--no-progress",
            "--print",
            "after_move:filepath",  # print final file path on success
        ]

        proxy = self.config.proxy()
        if proxy:
            cmd.extend(["--proxy", proxy])

        base_timeout = self.config.search_timeout()
        retry_intervals = [base_timeout, base_timeout * 2, base_timeout * 3]

        last_error = None
        for attempt, timeout in enumerate(retry_intervals, 1):
            try:
                logger.info(
                    f"[MusicShare] Searching YouTube (attempt {attempt}/3, timeout={timeout}s): {query}"
                )
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )

                stdout_text = stdout.decode("utf-8", errors="replace").strip()
                stderr_text = stderr.decode("utf-8", errors="replace").strip()

                if proc.returncode != 0:
                    last_error = f"yt-dlp exit code {proc.returncode}: {stderr_text[:200]}"
                    logger.warning(f"[MusicShare] {last_error}")
                    continue

                # yt-dlp prints the final filepath on stdout (due to --print)
                if stdout_text:
                    filepath = Path(stdout_text.split("\n")[-1].strip())
                    if filepath.exists():
                        logger.info(f"[MusicShare] Downloaded: {filepath}")
                        return filepath

                # Fallback: scan download_dir for newest file
                audio_files = sorted(
                    download_dir.glob(f"*.{self.config.audio_format()}"),
                    key=os.path.getmtime,
                    reverse=True,
                )
                if audio_files:
                    filepath = audio_files[0]
                    logger.info(f"[MusicShare] Found downloaded file: {filepath}")
                    return filepath

                last_error = "yt-dlp completed but no file found"
                logger.warning(f"[MusicShare] {last_error}")

            except asyncio.TimeoutError:
                last_error = f"timed out after {timeout}s"
                logger.warning(f"[MusicShare] Attempt {attempt}/3 {last_error}")
            except Exception as e:
                last_error = str(e)
                logger.error(f"[MusicShare] yt-dlp error: {e}")
                continue

        logger.error(
            f"[MusicShare] All 3 retries exhausted for '{query}'. "
            f"Last error: {last_error}"
        )
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