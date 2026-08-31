"""PIL slide rendering adapter — modern, high-converting slideshow slides.

Renders styled 720x1280 (or 720x720) slides with:
  - AI-generated or gradient backgrounds
  - Bold centered typography
  - Accent color for emphasis words
  - Minimal design — one idea per slide

Supports two background modes:
  1. Generated gradient (default, free)
  2. AI background image via background_path — loads the image, applies a dark
     overlay for text readability, then composites text on top.
"""

import os

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
except ImportError:
    Image = None  # type: ignore[assignment, misc]

# -- Canvas sizes -------------------------------------------------------------

CANVAS_SIZES = {
    "9:16": (720, 1280),
    "1:1": (720, 720),
    "16:9": (1280, 720),
}

# -- Color palettes ------------------------------------------------------------

PALETTES = {
    "dark": {
        "bg_top": (12, 12, 14),
        "bg_bottom": (24, 24, 28),
        "headline_text": (245, 245, 245),
        "body_text": (180, 180, 185),
        "accent": (255, 178, 102),       # warm amber
        "cta_bg": (245, 245, 245),
        "cta_text": (12, 12, 14),
        "cta_subtitle": (180, 180, 185),
    },
    "dark_warm": {
        "bg_top": (18, 12, 10),
        "bg_bottom": (32, 20, 16),
        "headline_text": (250, 240, 230),
        "body_text": (200, 185, 175),
        "accent": (255, 160, 90),         # coral amber
        "cta_bg": (250, 240, 230),
        "cta_text": (18, 12, 10),
        "cta_subtitle": (200, 185, 175),
    },
    "dark_cool": {
        "bg_top": (8, 14, 20),
        "bg_bottom": (16, 26, 36),
        "headline_text": (230, 240, 250),
        "body_text": (170, 185, 200),
        "accent": (100, 200, 220),        # soft teal
        "cta_bg": (230, 240, 250),
        "cta_text": (8, 14, 20),
        "cta_subtitle": (170, 185, 200),
    },
    "midnight": {
        "bg_top": (15, 10, 25),
        "bg_bottom": (25, 15, 40),
        "headline_text": (240, 235, 250),
        "body_text": (185, 175, 200),
        "accent": (200, 160, 255),        # soft lavender
        "cta_bg": (240, 235, 250),
        "cta_text": (15, 10, 25),
        "cta_subtitle": (185, 175, 200),
    },
    "minimal": {
        "bg_top": (250, 250, 250),
        "bg_bottom": (235, 235, 238),
        "headline_text": (20, 20, 25),
        "body_text": (80, 80, 90),
        "accent": (220, 90, 60),          # warm red-orange
        "cta_bg": (20, 20, 25),
        "cta_text": (250, 250, 250),
        "cta_subtitle": (80, 80, 90),
    },
}

# Palette aliases — shorthand names that resolve to canonical palettes
PALETTE_ALIASES = {
    "warm": "dark_warm",
    "cool": "dark_cool",
}

# -- Font loading --------------------------------------------------------------

# Bundled fonts directory (TikTok Sans, SIL Open Font License)
_FONTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts")

# TikTok Sans — primary font, bundled with project
# 36pt optical size for headlines (display), 16pt for body text
_FONT_PATHS = {
    "black": [
        os.path.join(_FONTS_DIR, "TikTokSans36pt-Black.ttf"),
        "/Library/Fonts/SF-Pro-Display-Heavy.otf",
        "/Library/Fonts/SF-Pro-Display-Black.otf",
    ],
    "bold": [
        os.path.join(_FONTS_DIR, "TikTokSans36pt-ExtraBold.ttf"),
        "/Library/Fonts/SF-Pro-Display-Bold.otf",
        "/Library/Fonts/Arial Bold.ttf",
    ],
    "medium": [
        os.path.join(_FONTS_DIR, "TikTokSans16pt-Medium.ttf"),
        "/Library/Fonts/SF-Pro-Display-Medium.otf",
    ],
    "regular": [
        os.path.join(_FONTS_DIR, "TikTokSans16pt-Regular.ttf"),
        "/Library/Fonts/SF-Pro-Display-Regular.otf",
        "/Library/Fonts/Arial.ttf",
    ],
}


def _load_font(size: int, weight: str = "bold") -> "ImageFont.ImageFont":
    paths = _FONT_PATHS.get(weight, _FONT_PATHS["bold"])
    for path in paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


# -- Background ----------------------------------------------------------------

def _make_gradient(width: int, height: int, top: tuple, bottom: tuple) -> "Image.Image":
    """Smooth vertical gradient background."""
    img = Image.new("RGB", (width, height))
    pixels = img.load()
    for y in range(height):
        t = y / max(height - 1, 1)
        # Ease-in-out curve for smoother gradient
        t = t * t * (3 - 2 * t)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        for x in range(width):
            pixels[x, y] = (r, g, b)
    return img


def _add_subtle_noise(img: "Image.Image", intensity: int = 3) -> "Image.Image":
    """Add very subtle noise for depth (not paper texture)."""
    import random
    rng = random.Random(42)
    pixels = img.load()
    w, h = img.size
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if rng.random() < 0.08:
                r, g, b = pixels[x, y]
                delta = rng.randint(-intensity, intensity)
                pixels[x, y] = (
                    max(0, min(255, r + delta)),
                    max(0, min(255, g + delta)),
                    max(0, min(255, b + delta)),
                )
    return img


def _load_background(
    path: str, width: int, height: int, overlay_opacity: float = 0.55
) -> "Image.Image":
    """Load an AI-generated background, resize/crop to canvas, and darken for text readability."""
    bg = Image.open(path).convert("RGB")

    # Resize to cover canvas (crop center if aspect ratios differ)
    bg_ratio = bg.width / bg.height
    canvas_ratio = width / height
    if bg_ratio > canvas_ratio:
        # Wider than canvas — fit height, crop width
        new_h = height
        new_w = int(height * bg_ratio)
    else:
        # Taller than canvas — fit width, crop height
        new_w = width
        new_h = int(width / bg_ratio)
    bg = bg.resize((new_w, new_h), Image.LANCZOS)

    # Center crop
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    bg = bg.crop((left, top, left + width, top + height))

    # Slight blur for depth
    bg = bg.filter(ImageFilter.GaussianBlur(radius=2))

    # Darken with semi-transparent black overlay for text readability
    overlay = Image.new("RGB", (width, height), (0, 0, 0))
    bg = Image.blend(bg, overlay, overlay_opacity)

    # Reduce saturation slightly so text pops
    enhancer = ImageEnhance.Color(bg)
    bg = enhancer.enhance(0.7)

    return bg


# -- Text helpers --------------------------------------------------------------

def _measure_text(
    draw: "ImageDraw.ImageDraw", text: str, font: "ImageFont.ImageFont"
) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _wrap_text(
    draw: "ImageDraw.ImageDraw",
    text: str,
    font: "ImageFont.ImageFont",
    max_width: int,
) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        w, _ = _measure_text(draw, test, font)
        if w <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines if lines else [text]


def _draw_centered_text(
    draw: "ImageDraw.ImageDraw",
    lines: list[str],
    font: "ImageFont.ImageFont",
    center_x: int,
    start_y: int,
    color: tuple,
    line_spacing: float = 1.4,
) -> int:
    """Draw horizontally centered text lines. Returns y after last line."""
    y = start_y
    for line in lines:
        w, h = _measure_text(draw, line, font)
        draw.text((center_x - w // 2, y), line, font=font, fill=color)
        y += int(h * line_spacing)
    return y


def _draw_accent_text(
    draw: "ImageDraw.ImageDraw",
    lines: list[str],
    font: "ImageFont.ImageFont",
    center_x: int,
    start_y: int,
    base_color: tuple,
    accent_color: tuple,
    accent_words: list[str] | None = None,
    line_spacing: float = 1.4,
) -> int:
    """Draw centered text with specific words in accent color."""
    if not accent_words:
        return _draw_centered_text(draw, lines, font, center_x, start_y, base_color, line_spacing)

    accent_lower = {w.lower().strip(".,!?") for w in accent_words}
    y = start_y
    for line in lines:
        # Measure full line for centering
        full_w, h = _measure_text(draw, line, font)
        x = center_x - full_w // 2
        # Draw word by word
        words = line.split(" ")
        for word in words:
            word_clean = word.lower().strip(".,!?;:'\"")
            color = accent_color if word_clean in accent_lower else base_color
            draw.text((x, y), word, font=font, fill=color)
            word_w, _ = _measure_text(draw, word + " ", font)
            x += word_w
        y += int(h * line_spacing)
    return y


def _draw_rounded_rect(
    draw: "ImageDraw.ImageDraw",
    xy: tuple[int, int, int, int],
    radius: int,
    fill: tuple,
) -> None:
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)


def _draw_accent_line(
    draw: "ImageDraw.ImageDraw",
    center_x: int,
    y: int,
    width: int,
    color: tuple,
    thickness: int = 3,
) -> None:
    """Draw a short horizontal accent line."""
    x0 = center_x - width // 2
    draw.rectangle([x0, y, x0 + width, y + thickness], fill=color)


# -- Main render ---------------------------------------------------------------

def render_slide(config: dict, output_path: str) -> tuple[int, int]:
    """Render a single slide to output_path. Returns (width, height)."""
    if Image is None:
        raise ImportError(
            "Pillow is required for pil_render adapter. Install with: pip install Pillow"
        )

    ar = config.get("aspect_ratio", "9:16")
    width, height = CANVAS_SIZES.get(ar, CANVAS_SIZES["9:16"])

    # Resolve palette (support legacy names)
    style = config.get("style", "dark")
    style = PALETTE_ALIASES.get(style, style)
    colors = dict(PALETTES.get(style, PALETTES["dark"]))

    # Override accent color if specified
    accent_hex = config.get("accent_color", "")
    if accent_hex:
        accent_hex = accent_hex.lstrip("#")
        if len(accent_hex) == 6:
            colors["accent"] = (
                int(accent_hex[0:2], 16),
                int(accent_hex[2:4], 16),
                int(accent_hex[4:6], 16),
            )

    slide_type = config.get("type", "content")
    headline = config.get("headline", "")
    body_raw = config.get("body", "")
    body_text = body_raw if isinstance(body_raw, str) else " ".join(body_raw) if body_raw else ""
    accent_words = config.get("accent_words", [])
    background_path = config.get("background_path", "")

    # Font sizes — TikTok Sans Black for headlines, Medium for body
    scale = width / 720
    font_headline = _load_font(int(64 * scale), "black")
    font_body = _load_font(int(36 * scale), "medium")
    font_cta_main = _load_font(int(56 * scale), "black")
    font_cta_sub = _load_font(int(32 * scale), "regular")

    # Build background
    if background_path and os.path.exists(background_path):
        img = _load_background(background_path, width, height, config.get("overlay_opacity", 0.55))
    else:
        img = _make_gradient(width, height, colors["bg_top"], colors["bg_bottom"])
        img = _add_subtle_noise(img)
    draw = ImageDraw.Draw(img)

    cx = width // 2
    content_width = int(width * 0.78)  # ~78% of canvas width for text

    if slide_type == "cta":
        # CTA slide — centered text with accent line and pill button
        cta_text = config.get("cta_text", headline)
        subtitle = body_text

        cta_lines = _wrap_text(draw, cta_text, font_cta_main, content_width)
        cta_block_h = sum(_measure_text(draw, l, font_cta_main)[1] for l in cta_lines)
        cta_block_h += int(len(cta_lines) * _measure_text(draw, "A", font_cta_main)[1] * 0.4)

        sub_h = 0
        if subtitle:
            sub_h = _measure_text(draw, subtitle, font_cta_sub)[1] + 30

        total_h = 20 + cta_block_h + sub_h + 3  # accent line + text + subtitle
        start_y = (height - total_h) // 2

        # Accent line above CTA
        _draw_accent_line(draw, cx, start_y, 60, colors["accent"], 3)
        start_y += 30

        # CTA text
        y = _draw_centered_text(draw, cta_lines, font_cta_main, cx, start_y, colors["cta_bg"], 1.3)

        # Subtitle below
        if subtitle:
            sub_lines = _wrap_text(draw, subtitle, font_cta_sub, content_width)
            _draw_centered_text(draw, sub_lines, font_cta_sub, cx, y + 20, colors["cta_subtitle"], 1.3)

    else:
        # Content/text/quote/stat slide — bold centered headline + optional body
        hl_spacing = 1.35
        body_spacing = 1.4
        hl_body_gap = 24  # fixed gap between headline block and body block

        hl_lines = _wrap_text(draw, headline, font_headline, content_width)
        hl_line_h = _measure_text(draw, "Ag", font_headline)[1]
        # N lines, but last line has no extra spacing below
        hl_block_h = int(hl_line_h * hl_spacing * len(hl_lines) - hl_line_h * (hl_spacing - 1))

        body_lines = []
        body_block_h = 0
        if body_text:
            body_lines = _wrap_text(draw, body_text, font_body, content_width)
            body_line_h = _measure_text(draw, "Ag", font_body)[1]
            body_block_h = int(body_line_h * body_spacing * len(body_lines) - body_line_h * (body_spacing - 1))

        total_h = hl_block_h + (hl_body_gap + body_block_h if body_lines else 0)
        start_y = (height - total_h) // 2

        # Headline (with optional accent words)
        y = _draw_accent_text(
            draw, hl_lines, font_headline,
            cx, start_y,
            colors["headline_text"], colors["accent"],
            accent_words, hl_spacing,
        )

        # Body text — fixed gap below headline block
        if body_lines:
            # y already includes trailing spacing from last headline line; subtract it
            body_y = start_y + hl_block_h + hl_body_gap
            _draw_centered_text(
                draw, body_lines, font_body,
                cx, body_y,
                colors["body_text"], body_spacing,
            )

    # Save
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    img.save(output_path, "PNG", optimize=False)

    return width, height


# -- Adapter -------------------------------------------------------------------

@register("pil_render")
class PilRenderAdapter(Adapter):
    """Sync adapter for rendering slideshow slides with PIL."""

    @property
    def timeout_seconds(self) -> int:
        return 30

    @property
    def is_sync(self) -> bool:
        return True

    @property
    def input_types(self) -> dict[str, str]:
        return {}

    @property
    def output_type(self) -> str:
        return "image"

    def submit(self, config: dict) -> str:
        output_path = config["output_path"]
        self.log_prompt(config, {
            "type": config.get("type", "content"),
            "headline": config.get("headline", ""),
            "body": config.get("body", ""),
            "style": config.get("style", "dark"),
            "accent_words": config.get("accent_words", []),
            "background_path": config.get("background_path", ""),
        }, model="pil_render")
        render_slide(config, output_path)
        return output_path

    def poll(self, job_id: str) -> tuple[Status, dict]:
        return Status.COMPLETED, {"output": job_id}

    def get_result(self, job_id: str) -> str:
        return job_id
