"""Generate an Apple-style music info card – AstrBot AnyMusic plugin.
Single unified frosted-glass background for consistent look across all platforms."""

import io
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw, ImageFilter, ImageFont


# ── Layout ───────────────────────────────────────────────────────────
COVER_SIZE = 440
CORNER_R = 48
BADGE_R = 28

PAD_OUTER = 28
PAD_INNER = 26
GAP = 32

PANEL_W = 500
CARD_W = PAD_OUTER + COVER_SIZE + GAP + PANEL_W + PAD_OUTER
CARD_H = PAD_OUTER + COVER_SIZE + PAD_OUTER

COVER_X = PAD_OUTER
COVER_Y = PAD_OUTER
TEXT_X = COVER_X + COVER_SIZE + GAP
TEXT_MAX_W = PANEL_W - PAD_INNER * 2

# ── Colours ──────────────────────────────────────────────────────────
GLASS_BG     = (30, 32, 38, 215)
GLASS_BORDER = (255, 255, 255, 15)
SHADOW_COLOR = (0, 0, 0, 60)

ACCENT_COLOR = (255, 130, 145)
TITLE_COLOR  = (248, 248, 255)
TEXT_COLOR   = (210, 214, 228)
LABEL_COLOR  = (150, 155, 170)
CREDIT_COLOR = (100, 105, 120)
BADGE_TEXT   = "white"


# ── Font loader ──────────────────────────────────────────────────────

def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load wqy-zenhei (CJK + Latin).  Fall back to DejaVu if unavailable."""
    paths = [
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for fp in paths:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _auto_crop_cover(im: Image.Image) -> Image.Image:
    bg = Image.new("RGBA", im.size, (255, 255, 255, 0))
    bg.paste(im, (0, 0), im)
    gray = bg.convert("L")
    bbox = gray.point(lambda p: 0 if p > 250 else 255).getbbox()
    if bbox:
        return im.crop(bbox)
    return im


async def download_cover(cover_url: str, proxy: str = "") -> Image.Image:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    kwargs = {"headers": headers, "timeout": aiohttp.ClientTimeout(total=15)}
    if proxy:
        kwargs["proxy"] = proxy
    async with aiohttp.ClientSession() as session:
        async with session.get(cover_url, **kwargs) as resp:
            data = await resp.read()
    return Image.open(io.BytesIO(data)).convert("RGBA")


def _round_corners(im: Image.Image, r: int) -> Image.Image:
    """Round corners with 2x supersampling for smooth anti-aliased edges."""
    scale = 2
    w, h = im.size
    big = (w * scale, h * scale)
    mask = Image.new("L", big, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, *big), r * scale, fill=255)
    mask = mask.resize(im.size, Image.LANCZOS)
    result = Image.new("RGBA", im.size)
    result.paste(im, mask=mask)
    return result


# ── Card builder ─────────────────────────────────────────────────────

async def make_info_card(
    cover_url: str,
    title: str,
    artist: str,
    album: str = "",
    source: str = "",
    proxy: str = "",
    duration: str = "",
    release_date: str = "",
) -> Image.Image:
    """Create a music card — unified frosted-glass background."""

    card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)

    # ── Card shadow (full rectangle, not rounded — avoids white corners on phone) ──
    so = 10
    shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rectangle(
        (so, so, CARD_W - so, CARD_H - so), fill=SHADOW_COLOR,
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    card.paste(shadow, mask=shadow)

    # ── Unified frosted-glass background (full rectangle) ──
    draw.rectangle((0, 0, CARD_W, CARD_H), fill=GLASS_BG)

    # ── Cover art ──
    cover = await download_cover(cover_url, proxy)
    cover = _auto_crop_cover(cover)
    cover = cover.resize((COVER_SIZE, COVER_SIZE), Image.LANCZOS)
    cover = _round_corners(cover, CORNER_R)
    card.paste(cover, (COVER_X, COVER_Y), cover)

    # ── Fonts & row heights ──
    font_title  = _load_font(44, bold=True)
    font_sub    = _load_font(30, bold=True)
    font_meta   = _load_font(26)
    font_label  = _load_font(22)
    font_credit = _load_font(20)
    font_badge  = _load_font(22, bold=True)

    title_line_h = 54
    sub_line_h   = 48
    meta_line_h  = 44
    gap_big = 18
    gap_sm  = 12
    badge_h = 38

    # ── Draw text top-down ──
    y = COVER_Y + PAD_INNER

    # Source badge — centered above title
    source_display = source.replace("_", " ").title()
    badge_text = f"  {source_display}  "
    badge_text_w = font_badge.getlength(badge_text)
    badge_bbox = font_badge.getbbox(badge_text)
    badge_text_h = badge_bbox[3] - badge_bbox[1]
    badge_x = TEXT_X + (PANEL_W - badge_text_w) // 2
    badge_pad = 6
    draw.rounded_rectangle(
        (badge_x - badge_pad, y,
         badge_x + badge_text_w + badge_pad, y + badge_h),
        BADGE_R, fill=ACCENT_COLOR,
    )
    # Vertical center: shift up a bit more — wqy-zenhei Latin baseline sits low
    text_y = y + (badge_h - badge_text_h) // 2 - 3
    draw.text((badge_x, text_y), badge_text, font=font_badge, fill=BADGE_TEXT)
    y += badge_h + gap_big

    # Title — centered
    for line in _wrap_text(title, font_title, TEXT_MAX_W):
        bb = font_title.getbbox(line)
        lw = bb[2] - bb[0]
        cx = TEXT_X + (PANEL_W - lw) // 2
        draw.text((cx, y), line, font=font_title, fill=TITLE_COLOR)
        y += title_line_h

    y += gap_big

    # Artist
    draw.text((TEXT_X + PAD_INNER, y), f"艺术家  {artist}", font=font_sub, fill=TEXT_COLOR)
    y += sub_line_h + gap_big

    # Metadata
    if album:
        _draw_label_value(draw, TEXT_X + PAD_INNER, y, "专辑", album,
                          font_label, font_meta, TEXT_MAX_W, LABEL_COLOR, TEXT_COLOR)
        y += meta_line_h
    if duration:
        _draw_label_value(draw, TEXT_X + PAD_INNER, y, "时长", duration,
                          font_label, font_meta, TEXT_MAX_W, LABEL_COLOR, TEXT_COLOR)
        y += meta_line_h
    if release_date:
        _draw_label_value(draw, TEXT_X + PAD_INNER, y, "发行", release_date,
                          font_label, font_meta, TEXT_MAX_W, LABEL_COLOR, TEXT_COLOR)
        y += meta_line_h

    # ── Credit line pinned to cover bottom ──
    credit_text = "由AstrBot AnyMusic插件生成"
    credit_h = 28
    credit_y = COVER_Y + COVER_SIZE - credit_h
    cb = font_credit.getbbox(credit_text)
    cw = cb[2] - cb[0]
    cx_credit = TEXT_X + (PANEL_W - cw) // 2
    draw.text((cx_credit, credit_y), credit_text, font=font_credit, fill=CREDIT_COLOR)

    return card


def _draw_label_value(draw, x, y, label, value, font_label, font_value, max_w,
                      label_color, value_color):
    prefix = f"{label}  "
    pw = font_label.getbbox(prefix)[2] - font_label.getbbox(prefix)[0]
    draw.text((x, y), prefix, font=font_label, fill=label_color)
    vw = max_w - pw
    vt = _truncate(value, font_value, vw)
    draw.text((x + pw, y), vt, font=font_value, fill=value_color)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    if not text:
        return []
    lines = []
    current = ""
    for ch in text:
        test = current + ch
        bbox = font.getbbox(test)
        if bbox[2] - bbox[0] > max_w and current:
            lines.append(current)
            current = ch
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def _truncate(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> str:
    if not text:
        return ""
    bbox = font.getbbox(text)
    if bbox[2] - bbox[0] <= max_w:
        return text
    while text and font.getbbox(text + "...")[2] - font.getbbox(text + "...")[0] > max_w:
        text = text[:-1]
    return text + "..."