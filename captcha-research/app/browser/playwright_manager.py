"""Gerencia uma sessão Playwright exclusiva (Browser Use usa sessão própria)."""
from __future__ import annotations

from pathlib import Path

from playwright.async_api import Browser, Page, Playwright, async_playwright

from app.captcha.captcha_detector import PageSnapshot


class PlaywrightManager:
    def __init__(self, headless: bool = False, timeout_ms: int = 30000):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self.page: Page | None = None

    async def __aenter__(self) -> "PlaywrightManager":
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless)
        ctx = await self._browser.new_context(locale="pt-BR")
        self.page = await ctx.new_page()
        self.page.set_default_timeout(self.timeout_ms)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def goto(self, url: str) -> int | None:
        resp = await self.page.goto(url, wait_until="domcontentloaded")
        try:
            await self.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass  # páginas com polling contínuo
        return resp.status if resp else None

    async def snapshot(self) -> PageSnapshot:
        html = await self.page.content()
        frames = [f.url for f in self.page.frames if f.url and f.url != "about:blank"]
        scripts = await self.page.eval_on_selector_all("script[src]", "els => els.map(e => e.src)")
        return PageSnapshot(html=html, frame_urls=frames, script_urls=scripts)

    async def fill_first(self, selectors: list[str], value: str) -> str | None:
        for sel in selectors:
            loc = self.page.locator(sel)
            if await loc.count():
                await loc.first.fill(value)
                return sel
        return None

    async def screenshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=str(path), full_page=True)
        return path
