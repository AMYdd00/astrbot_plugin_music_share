"""
astrbot_plugin_anymusic - AnyMusic 音乐插件

自动识别群聊中的 Apple Music / Spotify 分享链接，并提供 LLM 点歌工具。
"""

from pathlib import Path
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.event.filter import EventMessageType
from astrbot.api.message_components import File, Image, Record, file_to_base64
from astrbot.api.star import Context, Star, StarTools, register

from .config import ConfigHelper
from .cover_card import make_info_card
from .downloader import MusicDownloader
from .parsers.apple_music import AppleMusicParser, SongInfo
from .parsers.spotify import SpotifyParser
from .utils import extract_music_url, is_group_event, ResultCache


@register("astrbot_plugin_anymusic", "user", "AnyMusic", "1.0.0")
class MusicSharePlugin(Star):
    """Auto-detect music links & LLM song search tool."""

    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config
        self.config_helper = ConfigHelper(config)

        self.apple_parser = AppleMusicParser()
        self.spotify_parser = SpotifyParser()
        self.downloader = MusicDownloader(self.config_helper)
        self._cache = ResultCache(ttl_seconds=600)

    # ── LLM Tool: search_song ────────────────────────────────────────────

    @filter.llm_tool(name="search_song")
    async def search_song(self, event: AstrMessageEvent, song_name: str):
        '''在 YouTube 上搜索指定歌曲，下载音频并发送语音消息和文件到当前群聊。
        当用户说我想听XXX、放一首XXX、点歌XXX、搜一下XXX时使用此工具。

        Args:
            song_name(string): 歌曲名称，最好包含艺术家名以提高搜索准确性，如 周杰伦 晴天
        '''
        logger.info(f"[MusicShare] LLM 点歌: '{song_name}'")
        async for result in self._download_then_send(event, song_name, ""):
            yield result

    # ── Auto-detect music links ───────────────────────────────────────────

    @filter.event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """Check every message for Apple Music / Spotify links."""
        if is_group_event(event):
            try:
                group_id = str(event.get_group_id())
            except Exception:
                group_id = ""
            if group_id and not self.config_helper.is_group_enabled(group_id):
                return

        message_text = event.message_str or ""
        url = extract_music_url(message_text)
        if not url:
            return

        logger.info(f"[MusicShare] 检测到音乐分享链接: {url}")

        song_info = self._cache.get(url)
        if song_info:
            logger.info(f"[MusicShare] 缓存命中: {song_info.title}")
        else:
            song_info = await self._parse_url(url)
            if not song_info:
                logger.warning(f"[MusicShare] 无法解析链接: {url}")
                yield event.plain_result("无法识别该音乐链接")
                return
            self._cache.set(url, song_info)

        logger.info(f"[MusicShare] 解析成功: {song_info.title} - {song_info.artist}")

        # Send hand-drawn cartoon info card
        if song_info.cover_url:
            async for result in self._send_cover_card(event, song_info):
                yield result

        # Download and send audio
        async for result in self._download_then_send(event, song_info.title, song_info.artist):
            yield result

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _send_cover_card(self, event: AstrMessageEvent, song_info: SongInfo):
        """Generate and send the hand-drawn info card as an image."""
        try:
            proxy = self.config_helper.proxy() or ""
            card = await make_info_card(
                song_info.cover_url,
                song_info.title,
                song_info.artist,
                song_info.album,
                song_info.source,
                proxy,
                duration=song_info.duration,
                release_date=song_info.release_date,
            )
            temp_dir = Path(self.config_helper.download_dir() or "data/music")
            temp_dir.mkdir(parents=True, exist_ok=True)
            safe_name = song_info.title[:20].replace("/", "_")
            card_path = temp_dir / f"cover_{safe_name}.png"
            card.save(str(card_path), "PNG")
            # Use Image.fromFileSystem to send as image (not file)
            yield event.set_result(
                event.chain_result([Image.fromFileSystem(str(card_path))])
            )
            card_path.unlink()
        except Exception as e:
            logger.error(f"[MusicShare] 封面卡片生成失败: {e}")
            yield event.plain_result(
                f"歌名: {song_info.title}\n艺术家: {song_info.artist}\n来源: {song_info.source}"
            )

    async def _download_then_send(
        self, event: AstrMessageEvent, title: str, artist: str
    ):
        """Download audio and send voice + file."""
        download_dir = Path(StarTools.get_data_dir("music_share")) / "downloads"
        download_dir.mkdir(parents=True, exist_ok=True)

        audio_file = await self.downloader.search_and_download(
            title, artist, download_dir
        )

        if not audio_file:
            yield event.plain_result(f"未能在 YouTube 上找到 {title} {artist}".strip())
            return

        file_size_mb = audio_file.stat().st_size / (1024 * 1024)
        if file_size_mb > self.config_helper.max_file_size_mb():
            self.downloader.clean_file(audio_file)
            yield event.plain_result(f"音频文件过大 ({file_size_mb:.1f}MB)")
            return

        try:
            mode = self.config_helper.send_mode()
            if mode in ("仅语音", "都发送"):
                record = Record.fromFileSystem(str(audio_file))
                yield event.set_result(event.chain_result([record]))
            if mode in ("仅文件", "都发送"):
                file_b64 = file_to_base64(str(audio_file))
                file_component = File(name=audio_file.name, url=file_b64)
                yield event.set_result(event.chain_result([file_component]))
            logger.info(f"[MusicShare] 已发送: {audio_file.name} (mode={mode})")
        except Exception as e:
            logger.error(f"[MusicShare] 发送失败: {e}")
            yield event.plain_result(f"发送失败: {e}")

        self.downloader.clean_file(audio_file)

    async def _parse_url(self, url: str) -> Optional[SongInfo]:
        if AppleMusicParser.is_apple_music_url(url):
            return await self.apple_parser.parse(url)
        if SpotifyParser.is_spotify_url(url):
            return await self.spotify_parser.parse(url)
        return None