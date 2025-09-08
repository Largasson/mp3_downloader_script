# -*- coding: utf-8 -*-
"""
Печатает ссылку Bandcamp-поиска (tracks) и, если получится,
извлекает все ссылки /track/... с первой страницы.
В конце выбирает максимально подходящую ссылку по артисту/тайтлу (по URL-слугу).

Зависимости: requests, beautifulsoup4
Опционально для fallback: playwright (+ python -m playwright install chromium)

Запуск:
  python bc_find_track.py --artist "Efan" --title "Jacob's Ladder" [--debug]
"""

import argparse
import sys
import re
from typing import List, Optional, Tuple
from urllib.parse import quote_plus, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def build_bandcamp_search_url(artist: str, title: str, kind: str = "t") -> str:
    q = " ".join([p for p in [title, artist] if p]).strip()
    url = f"https://bandcamp.com/search?q={quote_plus(q)}"
    if kind in ("t", "a"):  # t=tracks, a=albums
        url += f"&item_type={kind}"
    return url


def parse_track_links_from_html(html: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    links, seen = [], set()
    for a in soup.select("a[href*='/track/']"):
        href = a.get("href") or ""
        if href and href not in seen:
            seen.add(href)
            links.append(href)
    return links


def fetch_html_via_requests(url: str) -> str:
    r = requests.get(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en,ru;q=0.9",
            "Referer": "https://bandcamp.com/",
        },
        timeout=30,
        allow_redirects=True,
    )
    if r.status_code == 200 and r.text:
        return r.text
    raise requests.HTTPError(f"status={r.status_code}")


def fetch_links_via_playwright(url: str, debug: bool = False) -> List[str]:
    # пробуем только если playwright установлен
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        if debug:
            print("[playwright] модуль не установлен — пропускаю fallback", file=sys.stderr)
        return []

    try:
        with sync_playwright() as pw:
            # если браузеры не установлены — поймаем исключение и тихо отдадим пусто
            try:
                browser = pw.chromium.launch(headless=True)
            except Exception as e:
                if debug:
                    print(f"[playwright] не удалось запустить Chromium ({e}). "
                          f"Установить: python -m playwright install chromium", file=sys.stderr)
                return []
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 1000},
                user_agent=UA,
                locale="en-US",
            )
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded")
            links = page.eval_on_selector_all("a[href*='/track/']", "els => els.map(e => e.href)") or []
            ctx.close()
            browser.close()
    except Exception as e:
        if debug:
            print(f"[playwright] ошибка: {e}", file=sys.stderr)
        links = []

    # убираем дубликаты
    seen, uniq = set(), []
    for u in links:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


# ---------- выбор лучшей ссылки по URL-слугу ----------
def normalize_text(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("’", "'").replace("‘", "'").replace("`", "'")
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def slugify_simple(s: str) -> str:
    s = normalize_text(s)
    s = re.sub(r"[^\w\s-]+", " ", s)      # пунктуацию -> пробел
    s = re.sub(r"\s+", "-", s).strip("-") # пробелы -> дефис
    return s

def title_slug_candidates(title: str) -> List[str]:
    t = title or ""
    v1 = slugify_simple(t)                       # jacob-s-ladder
    v2 = slugify_simple(t.replace("'", ""))      # jacobs-ladder
    v3 = slugify_simple(re.sub(r"\(.*?\)", " ", t))  # без скобок
    # убираем маркеры миксов
    MARKERS = r"(extended mix|original mix|edit|remix|radio edit|version|club mix)"
    v4 = slugify_simple(re.sub(MARKERS, " ", normalize_text(t)))
    out, seen = [], set()
    for v in (v1, v2, v3, v4):
        if v and v not in seen:
            seen.add(v); out.append(v)
    return out

def canonical_noquery(u: str) -> str:
    sp = urlsplit(u)
    return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))

def link_score(u: str, artist: str, title: str) -> Tuple[int, str]:
    """Возвращает (score, canonical_url). Оцениваем только по URL."""
    can = canonical_noquery(u)
    m = re.search(r"/track/([^/?#]+)", can)
    slug = (m.group(1).lower() if m else "")

    want_slugs = set(title_slug_candidates(title))
    score = 0
    if slug in want_slugs:
        score += 100  # точное совпадение слага

    # частичное совпадение по токенам
    slug_tokens = set(re.findall(r"\w+", slug.replace("-", " ")))
    title_tokens = set(re.findall(r"\w+", normalize_text(title)))
    score += 10 * len(slug_tokens & title_tokens)

    # слабый бонус, если artist встречается в subdomain *.bandcamp.com
    host = urlsplit(can).netloc
    if host.endswith(".bandcamp.com"):
        sub = host[:-len(".bandcamp.com")].replace("-", " ")
        if set(re.findall(r"\w+", normalize_text(artist))) & set(re.findall(r"\w+", sub)):
            score += 5

    return score, can

def pick_best_link(links: List[str], artist: str, title: str, debug: bool=False) -> Optional[str]:
    best_url, best_sc = None, -1
    for u in links:
        if "/track/" not in u:
            continue
        sc, can = link_score(u, artist, title)
        if debug:
            print(f"[score] {sc:3d} {can}", file=sys.stderr)
        if sc > best_sc:
            best_sc, best_url = sc, can
    return best_url


def find_on_bandcamp(args):


    url = build_bandcamp_search_url(args.artist, args.title, "t")
    # 1) всегда печатаем ссылку на страницу поиска
    # print(url)

    # 2) пытаемся достать ссылки через requests
    links: List[str] = []
    try:
        html = fetch_html_via_requests(url)
        links = parse_track_links_from_html(html)
        if args.debug:
            print(f"[requests] tracks found: {len(links)}", file=sys.stderr)
    except Exception as e:
        if args.debug:
            print(f"[requests] fail: {e}", file=sys.stderr)

    # 3) fallback на Playwright (если есть и установлен браузер)
    if not links:
        pl_links = fetch_links_via_playwright(url, debug=args.debug)
        if args.debug:
            print(f"[playwright] tracks found: {len(pl_links)}", file=sys.stderr)
        links = pl_links

    # # 4) выводим найденные трек-ссылки (по одной на строку)
    # for u in links:
    #     print(u)

    # 5) выбираем максимально подходящую ссылку
    if links:
        best = pick_best_link(links, args.artist, args.title, debug=args.debug)
        if best:
            # print(f"BEST: {best}")
            return best




if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Bandcamp search link + извлечение ссылок треков и выбор лучшей")
    ap.add_argument("--artist", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    print(find_on_bandcamp(args))
