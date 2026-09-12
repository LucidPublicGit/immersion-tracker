"""Crop LiT brand sources and emit extension + web icon assets.

Sources (defaults):
  app/web/static/brand/source-app-icon.jpg  — rounded app tile (toolbar / favicon)
  app/web/static/brand/source-banner.jpg    — horizontal wordmark banner

Usage (from repo root or anywhere):
  python scripts/process_brand_icons.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
BRAND_DIR = ROOT / "app" / "web" / "static" / "brand"
EXT_ICONS = ROOT / "extension" / "icons"

APP_SRC = BRAND_DIR / "source-app-icon.jpg"
BANNER_SRC = BRAND_DIR / "source-banner.jpg"

SIZES = (16, 32, 48, 64, 96, 128, 256)


def rounded_mask(size: int, radius_ratio: float = 0.22) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    r = max(1, int(size * radius_ratio))
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=r, fill=255)
    return mask


def make_icon_png(src: Image.Image, size: int) -> Image.Image:
    img = src.convert("RGBA")
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    if size <= 32:
        bg = Image.new("RGBA", (size, size), (10, 16, 28, 255))
        bg.alpha_composite(img)
        return bg.convert("RGBA")
    mask = rounded_mask(size, 0.20 if size >= 64 else 0.18)
    if size >= 48:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=0.6))
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def extract_app_tile(app: Image.Image) -> Image.Image:
    arr = np.asarray(app.convert("RGB"), dtype=np.float32)
    lum = arr.mean(axis=2)
    mask = lum > 18
    row = mask.mean(axis=1)
    col = mask.mean(axis=0)
    row_on = row > 0.04
    col_on = col > 0.04
    y_idx = np.where(row_on)[0]
    x_idx = np.where(col_on)[0]
    y0, y1 = int(y_idx[0]), int(y_idx[-1]) + 1
    x0, x1 = int(x_idx[0]), int(x_idx[-1]) + 1
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    side = max(x1 - x0, y1 - y0)
    side = int(min(side, app.width * 0.92, app.height * 0.72))
    left = int(cx - side / 2)
    top = int(cy - side / 2)
    left = max(0, min(left, app.width - side))
    top = max(0, min(top, app.height - side))
    tile = app.crop((left, top, left + side, top + side))
    inset = int(side * 0.04)
    return tile.crop((inset, inset, side - inset, side - inset))


def main() -> None:
    if not APP_SRC.is_file():
        raise SystemExit(f"Missing app icon source: {APP_SRC}")
    EXT_ICONS.mkdir(parents=True, exist_ok=True)
    BRAND_DIR.mkdir(parents=True, exist_ok=True)

    base = extract_app_tile(Image.open(APP_SRC).convert("RGB"))
    print("tile", base.size)

    for size in SIZES:
        out = make_icon_png(base, size)
        path = EXT_ICONS / f"icon-{size}.png"
        out.save(path, optimize=True)
        print("wrote", path)

    for size in (32, 64, 128, 256):
        make_icon_png(base, size).save(BRAND_DIR / f"icon-{size}.png", optimize=True)
    make_icon_png(base, 32).save(BRAND_DIR / "favicon-32.png", optimize=True)
    make_icon_png(base, 16).save(BRAND_DIR / "favicon-16.png", optimize=True)
    make_icon_png(base, 256).save(BRAND_DIR / "mark-256.png", optimize=True)

    if BANNER_SRC.is_file():
        banner = Image.open(BANNER_SRC).convert("RGB")
        for bw in (320, 640):
            bh = int(banner.height * (bw / banner.width))
            banner.resize((bw, bh), Image.Resampling.LANCZOS).save(
                BRAND_DIR / f"banner-{bw}.jpg", quality=90, optimize=True
            )
        print("wrote banners")

    print("done")


if __name__ == "__main__":
    main()
