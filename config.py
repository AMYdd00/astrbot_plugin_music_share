"""Configuration helper for astrbot_plugin_music_share."""

from pathlib import Path


class ConfigHelper:
    """Typed accessor for plugin configuration."""

    def __init__(self, config):
        self.config = config

    def _cfg(self, key: str, default=None):
        if not self.config:
            return default
        if isinstance(self.config, dict):
            return self.config.get(key, default)
        return getattr(self.config, key, default)

    # ---- proxy ----
    def proxy(self) -> str:
        return str(self._cfg("proxy", "") or "").strip()

    # ---- download ----
    def download_dir(self) -> str:
        return str(self._cfg("download_dir", "data/music"))

    def audio_format(self) -> str:
        return str(self._cfg("audio_format", "mp3"))

    def audio_quality(self) -> int:
        return int(self._cfg("audio_quality", 192))

    def max_file_size_mb(self) -> int:
        return int(self._cfg("max_file_size_mb", 50))

    def search_timeout(self) -> int:
        return int(self._cfg("search_timeout", 30))

    # ---- send mode ----
    def send_mode(self) -> str:
        return str(self._cfg("send_mode", "都发送")).strip()

    # ---- groups ----
    def enabled_groups(self) -> list[str]:
        groups = self._cfg("enabled_groups", [])
        if not groups:
            return []
        return [str(g) for g in groups]

    def is_group_enabled(self, group_id: str) -> bool:
        enabled = self.enabled_groups()
        if not enabled:
            return True
        return group_id in enabled