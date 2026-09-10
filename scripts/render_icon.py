"""Rasterize web/public/favicon.svg to icon-256.png via Chromium (exact SVG)."""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "web" / "public" / "favicon.svg"
OUT = ROOT / "web" / "public" / "icon-256.png"
SIZE = 256


def main() -> None:
    svg = SVG.read_text(encoding="utf-8")
    # Ensure explicit pixel size for crisp rasterization
    if 'width="' not in svg:
        svg = svg.replace("<svg ", f'<svg width="{SIZE}" height="{SIZE}" ', 1)

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;width:{SIZE}px;height:{SIZE}px;overflow:hidden">
{svg}
</body></html>"""

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": SIZE, "height": SIZE}, device_scale_factor=1)
        page.set_content(html, wait_until="load")
        page.screenshot(path=str(OUT), type="png", omit_background=False)
        browser.close()

    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
