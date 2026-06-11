# 🎵 AnyMusic

AstrBot 音乐插件 —— 自动识别群聊中的 Apple Music / Spotify 分享链接，生成信息卡片，搜索下载音频文件。

> 原名 `astrbot_plugin_music_share`，现已更名为 **astrbot_plugin_anymusic**。

## ✨ 功能

- 🔗 **自动识别链接** —— Apple Music / Spotify 分享链接自动解析歌名、艺术家、专辑、时长、发行日期
- 🖼️ **信息卡片** —— 磨砂玻璃风格卡片，展示专辑封面 + 歌曲信息 + 来源徽章
- 🎤 **语音消息** —— 发送 QQ 语音可直接点击播放
- 📁 **可下载文件** —— 同步发送音频文件
- 🤖 **LLM 点歌** —— 说「我想听夜曲」「放一首晴天」，Bot 自动搜索下载
- ⚙️ **灵活发送模式** —— 可选择仅发语音 / 仅发文件 / 同时发送
- 🚀 **异步非阻塞** —— 搜索下载不阻塞 Bot 主循环
- 💾 **内存缓存** —— 同一链接 10 分钟内复用解析结果
- 🧹 **自动清理** —— 发送完成后立即删除临时文件

## 📥 安装

### 方式一：WebUI 安装（推荐）

在 AstrBot WebUI 插件市场中搜索 `AnyMusic` 安装。

### 方式二：手动安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/AMYdd00/astrbot_plugin_anymusic.git
pip install -r astrbot_plugin_anymusic/requirements.txt
```

### 前置依赖

| 依赖 | 用途 |
|------|------|
| `yt-dlp` | YouTube 搜索 + 音频下载 |
| `ffmpeg` | 音频格式转换 |
| `beautifulsoup4` | Apple Music HTML 解析 |
| `aiohttp` | Spotify oEmbed API |
| `Pillow` | 信息卡片图片生成 |

```bash
pip install yt-dlp beautifulsoup4 aiohttp Pillow
```

## ⚙️ 配置

在 AstrBot WebUI → 插件管理 → AnyMusic → 配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `proxy` | 空 | HTTP 代理地址（如 `http://127.0.0.1:7890`） |
| `download_dir` | `data/music` | 临时下载目录 |
| `audio_format` | `mp3` | 音频格式 (mp3 / m4a / opus) |
| `audio_quality` | 192 | 音频质量 (kbps) |
| `max_file_size_mb` | 50 | 最大文件大小限制 (MB) |
| `search_timeout` | 30 | 搜索超时 (秒) |
| **`send_mode`** | **都发送** | **识别后发送方式：语音 / 文件 / 都发送** |
| `enabled_groups` | [] | 启用的群组列表，留空则所有群组生效 |

## 🔧 工作原理

```
用户分享 Apple Music / Spotify 链接
    │
    ▼
提取 URL → 判断平台
    │
    ├─ Apple Music: HTML 解析 <title> + JSON-LD → 歌名/艺术家/专辑/封面/时长/发行日期
    └─ Spotify: oEmbed API + HTML meta + JSON-LD → 同上
    │
    ▼
生成磨砂玻璃风格信息卡片 → 发送图片
    │
    ▼
yt-dlp 搜索 YouTube → 下载音频 → 按 send_mode 发送语音/文件
    │
    ▼
清理临时文件
```

## ❓ 常见问题

### Q: 为什么不直接从 Apple Music / Spotify 下载？

Apple Music 有 DRM 加密保护，Spotify 需要 Premium 账户。YouTube 是全球最大的免费音乐索引，yt-dlp 覆盖范围远超单平台。

### Q: 国区 Apple Music 链接能识别吗？

能。支持 `music.apple.com/cn/`、`/us/`、`/jp/` 等所有区域。

### Q: 为什么显示「无法识别该音乐链接」？

可能是网络问题导致访问 Apple Music/Spotify 页面超时。请检查代理设置。

## 📂 文件结构

```
astrbot_plugin_anymusic/
├── _conf_schema.json          # WebUI 配置定义
├── config.py                  # ConfigHelper
├── cover_card.py              # 信息卡片生成 (PIL)
├── downloader.py              # yt-dlp 下载封装
├── logo.png                   # 插件图标
├── main.py                    # 插件入口
├── metadata.yaml              # 元数据
├── README.md                  # 本文件
├── requirements.txt           # 依赖列表
├── utils.py                   # URL 提取 + ResultCache
└── parsers/
    ├── __init__.py
    ├── apple_music.py          # Apple Music 解析器
    └── spotify.py              # Spotify 解析器
```

## 🔗 链接

- GitHub: https://github.com/AMYdd00/astrbot_plugin_anymusic
- AstrBot: https://github.com/AstrBotDevs/AstrBot