# AnyMusic

AstrBot 音乐插件 —— 自动识别群聊中 10 大主流音乐平台分享链接，生成信息卡片，双引擎竞争下载高质量音频。

> 原名 `astrbot_plugin_music_share`，现已更名为 **astrbot_plugin_anymusic**。

## 功能

- **自动识别链接** —— 支持 10 个平台：Spotify / Apple Music / YouTube / SoundCloud / 网易云 / QQ 音乐 / 酷狗 / 酷我 / 咪咕 / Bilibili 音频
- **信息卡片** —— 磨砂玻璃风格卡片，展示专辑封面 + 歌曲信息 + 来源徽章
- **双引擎竞争下载** —— yt-dlp + spotdl 并行搜索，通过时长匹配 + 标题相似度 + 负面关键词过滤选出最优音源
- **时长精确匹配** —— 解析原始歌曲时长，候选偏差超过阈值自动拒绝（默认 99% 精度可配置）
- **语音消息** —— 发送 QQ 语音可直接点击播放
- **可下载文件** —— 同步发送音频文件
- **LLM 点歌** —— 说「我想听夜曲」「放一首晴天」，Bot 自动搜索下载
- **灵活发送模式** —— 可选择仅发语音 / 仅发文件 / 同时发送
- **跨平台兼容** —— 不支持语音的平台自动回退到文件发送
- **跨平台字体** —— 自动下载 Noto Sans SC 字体，Windows/Linux/macOS 均完美渲染中英文
- **异步非阻塞** —— 搜索下载不阻塞 Bot 主循环
- **内存缓存** —— 同一链接 10 分钟内复用解析结果
- **自动清理** —— 发送完成后立即删除临时文件

## 安装

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
| `spotdl` | Spotify ISRC 精确匹配 + YouTube Music 下载 |
| `ffmpeg` | 音频格式转换 |
| `beautifulsoup4` | HTML 解析（Apple Music / 国内平台） |
| `aiohttp` | 异步 HTTP 请求 |
| `Pillow` | 信息卡片图片生成 |
| `rapidfuzz` | 标题模糊匹配（spotdl 已附带） |

```bash
pip install yt-dlp spotdl beautifulsoup4 aiohttp Pillow
```

## 配置

在 AstrBot WebUI → 插件管理 → AnyMusic → 配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `proxy` | 空 | HTTP 代理地址（如 `http://127.0.0.1:7890`） |
| `download_dir` | `data/music` | 临时下载目录 |
| `audio_format` | `mp3` | 音频格式 (mp3 / m4a / opus) |
| `audio_quality` | 192 | 音频质量 (kbps) |
| `max_file_size_mb` | 50 | 最大文件大小限制 (MB) |
| `search_timeout` | 30 | 搜索超时 (秒) |
| `match_threshold` | 99 | 时长匹配精度 (%), 99 表示允许 ±1% 偏差 |
| `send_mode` | 都发送 | 识别后发送方式：语音 / 文件 / 都发送 |
| `enabled_groups` | [] | 启用的群组列表，留空则所有群组生效 |

## 支持的平台与解析方式

| 平台 | 解析方式 | 下载方式 |
|------|---------|---------|
| Spotify | oEmbed API + HTML meta + JSON-LD | 双引擎竞争 |
| Apple Music | HTML `<title>` + JSON-LD | 双引擎竞争 |
| YouTube / YouTube Music | yt-dlp `--dump-json` | 双引擎竞争 |
| SoundCloud | yt-dlp `--dump-json` | 双引擎竞争 |
| Bilibili 音频 (`/audio/au`) | yt-dlp `--dump-json` | 双引擎竞争 |
| 网易云音乐 | HTML `<title>` 解析 | 双引擎竞争 |
| QQ 音乐 | HTML `<title>` 解析 | 双引擎竞争 |
| 酷狗音乐 | HTML `<title>` 解析 | 双引擎竞争 |
| 酷我音乐 | HTML `<title>` 解析 | 双引擎竞争 |
| 咪咕音乐 | HTML `<title>` 解析 | 双引擎竞争 |

> 注意：Bilibili 仅识别纯音频链接 (`/audio/au\d+`)，不会拦截普通视频 (`/video/`)。

## 工作原理

```
用户分享音乐链接
    │
    ▼
正则路由表识别平台
    │
    ├─ Spotify / Apple Music → 精解析 (时长/封面/专辑等)
    ├─ YouTube / SoundCloud / Bili → yt-dlp 提取元数据
    └─ 网易云 / QQ / 酷狗 / 酷我 / 咪咕 → HTML <title> 解析
    │
    ▼
生成磨砂玻璃风格信息卡片 → 发送图片
    │
    ▼
双引擎竞争下载 (yt-dlp + spotdl)
    │
    ├─ yt-dlp --dump-json ytsearch3:   ──┐
    ├─ spotdl save <query> --save-file  ──┤ 并行
    │                                     │
    ├─ 多维评分:                            │
    │   时长匹配 40% + 标题相似 40%           │
    │   + 来源加分 20% + 负面词惩罚 -50%       │
    │                                     │
    └─ 选最优 → 下载单个文件
    │
    ▼
按 send_mode 发送语音/文件 → 清理临时文件
```

## 常见问题

### Q: 为什么不直接从 Apple Music / Spotify 下载？

Apple Music 有 DRM 加密保护，Spotify 需要 Premium 账户。本插件通过 ISRC 匹配 YouTube Music 官方音轨，绝大多数情况能下载到原曲录音室版本。

### Q: 为什么下载到纯音乐 / 伴奏 / 翻唱？

多维评分系统会自动过滤带有 `instrumental / karaoke / cover / remix` 等关键词的候选，并优先选择标题相似度高的结果。如果仍出现误匹配，可调高 `match_threshold`（如 100）。

### Q: 国区 Apple Music 链接能识别吗？

能。支持 `music.apple.com/cn/`、`/us/`、`/jp/` 等所有区域。

### Q: 为什么显示「无法识别该音乐链接」或「未找到匹配的歌曲」？

- 链接格式不被正则路由表匹配（检查是否支持该平台）
- 解析元数据时网络超时（检查代理设置）
- 候选音源时长偏差超过 `match_threshold` 阈值（可适当降低阈值）

## 文件结构

```
astrbot_plugin_anymusic/
├── _conf_schema.json          # WebUI 配置定义
├── config.py                  # ConfigHelper
├── cover_card.py              # 信息卡片生成 (PIL) + 字体自动下载
├── downloader.py              # 双引擎竞争下载 (yt-dlp + spotdl)
├── logo.png                   # 插件图标
├── main.py                    # 插件入口 + 路由分发
├── metadata.yaml              # 元数据
├── README.md                  # 本文件
├── requirements.txt           # 依赖列表
├── utils.py                   # URL 路由表 + HTML 标题解析 + ResultCache
└── parsers/
    ├── __init__.py
    ├── apple_music.py          # Apple Music 精解析器
    └── spotify.py              # Spotify 精解析器
```

## 链接

- GitHub: https://github.com/AMYdd00/astrbot_plugin_anymusic
- AstrBot: https://github.com/AstrBotDevs/AstrBot