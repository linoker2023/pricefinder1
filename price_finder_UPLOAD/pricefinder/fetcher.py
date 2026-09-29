"""Загрузка HTML: requests + ретраи, robots.txt, опционально Playwright для JS-сайтов."""

from __future__ import annotations

import random
import sys
import time
import urllib.error
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_FALLBACK_UAS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]


class FetchError(RuntimeError):
    pass


@dataclass
class FetchResult:
    url: str
    status: int = 0
    html: str = ""
    engine: str = "requests"
    error: str = ""
    elapsed: float = 0.0
    ok: bool = False


@dataclass
class Fetcher:
    timeout: float = 20.0
    retries: int = 3
    delay: float = 1.0
    respect_robots: bool = True
    user_agent: str = ""
    proxy: str = ""
    insecure: bool = False
    use_browser: bool | None = None  # None = по флагу сайта
    verbose: bool = False
    session: requests.Session = field(default_factory=requests.Session, repr=False)
    _robots: dict[str, urllib.robotparser.RobotFileParser] = field(default_factory=dict, repr=False)
    _browser: object | None = field(default=None, repr=False)

    # --- robots.txt -------------------------------------------------------
    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._robots.get(host)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(host + "/robots.txt")
            try:
                resp = self.session.get(host + "/robots.txt", timeout=8, headers=DEFAULT_HEADERS)
                if resp.status_code < 400:
                    rp.parse(resp.text.splitlines())
                else:
                    rp.allow_all = True  # type: ignore[attr-defined]
            except Exception:
                rp.allow_all = True  # type: ignore[attr-defined]
            self._robots[host] = rp
        try:
            return bool(rp.can_fetch(self.user_agent or DEFAULT_HEADERS["User-Agent"], url))
        except Exception:
            return True

    # --- основной метод ---------------------------------------------------
    def get(
        self,
        url: str,
        *,
        method: str = "GET",
        post_data: dict | None = None,
        headers: dict | None = None,
        cookies: dict | None = None,
        js_render: bool = False,
        render_wait: float = 2.5,
        wait_selector: str = "",
    ) -> FetchResult:
        started = time.time()
        need_browser = self.use_browser if self.use_browser is not None else js_render

        if not self.allowed(url):
            self._log(f"  [robots.txt] доступ запрещён: {url}")
            return FetchResult(url=url, error="robots.txt disallow")

        if need_browser:
            result = self._get_with_browser(url, render_wait=render_wait, wait_selector=wait_selector)
            result.elapsed = time.time() - started
            return result

        last_error = ""
        for attempt in range(1, max(1, self.retries) + 1):
            hdrs = dict(DEFAULT_HEADERS)
            if headers:
                hdrs.update(headers)
            if attempt > 1:
                hdrs["User-Agent"] = random.choice(_FALLBACK_UAS)
                time.sleep(self.delay * attempt + random.uniform(0, 0.6))
            elif self.delay:
                time.sleep(random.uniform(0.2, max(0.3, self.delay)))
            try:
                resp = self.session.request(
                    method=method.upper(),
                    url=url,
                    json=post_data if method.upper() == "JSON" else None,
                    data=post_data if method.upper() == "POST" else None,
                    headers=hdrs,
                    cookies=cookies or None,
                    timeout=self.timeout,
                    proxies={"http": self.proxy, "https": self.proxy} if self.proxy else None,
                    verify=not self.insecure,
                )
                if resp.status_code == 200:
                    return FetchResult(
                        url=url,
                        status=200,
                        html=resp.text,
                        engine="requests",
                        ok=True,
                        elapsed=time.time() - started,
                    )
                if resp.status_code in (403, 429, 503):
                    last_error = f"HTTP {resp.status_code} (антибот/лимит)"
                    self._log(f"  попытка {attempt}: {last_error} — {url}")
                    if attempt >= self.retries:
                        break
                    continue
                last_error = f"HTTP {resp.status_code}"
                break
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self._log(f"  попытка {attempt}: {last_error}")
        return FetchResult(url=url, error=last_error or "неизвестная ошибка", elapsed=time.time() - started)

    # --- браузерный рендер ------------------------------------------------
    def _get_with_browser(self, url: str, render_wait: float = 2.5, wait_selector: str = "") -> FetchResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return FetchResult(
                url=url,
                error="нужен Playwright: pip install playwright && playwright install chromium",
            )
        started = time.time()
        try:
            if self._browser is None:
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(  # type: ignore[attr-defined]
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
            context = self._browser.new_context(  # type: ignore[attr-defined]
                user_agent=self.user_agent or DEFAULT_HEADERS["User-Agent"],
                locale="ru-RU",
                viewport={"width": 1440, "height": 900},
            )
            page = context.new_page()
            resp = page.goto(url, wait_until="domcontentloaded", timeout=int(self.timeout * 1000))
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=int(render_wait * 2000))
                except Exception:
                    pass
            else:
                page.wait_for_timeout(int(render_wait * 1000))
            html = page.content()
            status = resp.status if resp else 200
            context.close()
            return FetchResult(
                url=url, status=status, html=html, engine="playwright", ok=status == 200,
                elapsed=time.time() - started,
            )
        except Exception as exc:
            return FetchResult(url=url, error=f"browser: {type(exc).__name__}: {exc}", elapsed=time.time() - started)

    def close(self) -> None:
        try:
            if self._browser is not None:
                self._browser.close()  # type: ignore[attr-defined]
                self._playwright.stop()  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            self.session.close()
        except Exception:
            pass

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg, file=sys.stderr)
