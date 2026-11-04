"""Tira as capturas de ecrã do README a partir do sistema a correr com dados reais.

Uso (com `docker compose up` a correr há pelo menos umas horas):

    uv run --with playwright python scripts/screenshots.py
    # (na primeira vez: uv run --with playwright playwright install chromium)
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = Path(__file__).resolve().parent.parent / "docs" / "img"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=2)

        page.goto(BASE + "/")
        page.wait_for_function("document.getElementById('n').textContent !== '–'", timeout=30_000)
        page.wait_for_timeout(8_000)  # deixa chegar alguns deltas e carregar os tiles
        page.screenshot(path=OUT / "map.png")

        page.goto(BASE + "/analytics")
        page.wait_for_selector("#lines tr", timeout=30_000)
        page.wait_for_timeout(2_000)
        page.screenshot(path=OUT / "analytics.png", full_page=True)
        browser.close()
    print("capturas em", OUT)


if __name__ == "__main__":
    main()
