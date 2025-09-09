from typing import List
import logging
from urllib.parse import urlsplit, urlunsplit

from config.settings import USER_AGENT, PW_TIMEOUT

def _canonical_noquery(u: str) -> str:
    sp = urlsplit(u)
    return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))

def fetch_links_via_playwright(search_url: str, *, logger: logging.Logger) -> List[str]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        logger.warning("playwright module not available: %s", e)
        return []

    links: List[str] = []

    with sync_playwright() as pw:
        browser = None
        # 1) системный Chrome (если есть)
        try:
            browser = pw.chromium.launch(channel="chrome", headless=True)
        except Exception:
            # 2) bundled Chromium
            try:
                browser = pw.chromium.launch(headless=True)
            except Exception as e2:
                logger.warning("playwright launch failed: %s", e2)
                return []

        ctx = browser.new_context(
            viewport={"width": 1280, "height": 1000},
            user_agent=USER_AGENT,
            locale="en-US",
        )

        # блокируем тяжёлые ресурсы и аналитику
        def _route(route):
            req = route.request
            if req.resource_type in {"image", "media", "font"}:
                return route.abort()
            if any(x in req.url for x in ("googletagmanager.com", "google-analytics.com", "doubleclick.net")):
                return route.abort()
            return route.continue_()

        ctx.route("**/*", _route)
        page = ctx.new_page()
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=PW_TIMEOUT * 1000)
            # гарантируем item_type=t
            if "item_type=t" not in page.url:
                page.evaluate("""
                    () => {
                      const u = new URL(location.href);
                      u.searchParams.set('item_type', 't');
                      if (location.href !== u.toString()) location.href = u.toString();
                    }
                """)
                page.wait_for_url(lambda url: "item_type=t" in url, timeout=PW_TIMEOUT * 1000)

            links = page.eval_on_selector_all(
                "a[href*='/track/']",
                "els => Array.from(new Set(els.map(e => e.href)))"
            ) or []

        finally:
            ctx.close()
            browser.close()

    # Канонизируем (без query), но возвращаем ещё и «сырые» можно наверху.
    return [_canonical_noquery(u) for u in links]
