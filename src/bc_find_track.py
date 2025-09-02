# bc_find_bandcamp.py
# -*- coding: utf-8 -*-
"""
Надёжный поиск страницы трека/альбома на Bandcamp по артисту и названию.

Алгоритм (без ручных флажков):
  1) bandcamp.com/search?q=<title> <artist> → собираем *.bandcamp.com/track|album/…
  2) Ранжирование кандидатов: title (текст/slug) > byline (перформер) > host (поддомен)
  3) Жёсткая ВАЛИДАЦИЯ кандидата:
       - GET -> 200 и страница «похожа» на трек/альбом + совпадают токены названия и артиста → ok
       - GET -> 403 → делаем HEAD; если НЕ 404 → ok (антибот), иначе отбрасываем
       - иначе → отбрасываем
  4) Если 1–3 не дали результата — аккуратно пробуем slug-и на поддоменах артиста (artist без пробелов/с дефисами),
     но тоже ТОЛЬКО через валидацию как выше.
  5) Возвращаем КАНОНИЧЕСКИЙ URL (og:url / rel=canonical) или финальный после редиректа. Иначе — NOT FOUND.

Зависимости: pip install requests beautifulsoup4
(опц.)      pip install html5lib или lxml — устойчивее парсинг HTML
"""

from __future__ import annotations

import argparse
import random
import re
import time
import unicodedata
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter, Retry

BANDCAMP = "https://bandcamp.com"

# ---------- HTML parser fallback ----------
try:
    import lxml  # noqa: F401
    _PARSER = "lxml"
except Exception:
    try:
        import html5lib  # noqa: F401
        _PARSER = "html5lib"
    except Exception:
        _PARSER = "html.parser"

def BS(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, _PARSER)

# ---------- HTTP with retries ----------
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
]

def make_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.headers.update({
        "User-Agent": random.choice(UA_POOL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru,en;q=0.9",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    return s

SESSION = make_session()

def http_get(url: str, *, referer: Optional[str] = None, timeout: int = 25) -> requests.Response:
    headers: Dict[str, str] = {}
    if referer:
        headers["Referer"] = referer
    if random.random() < 0.25:
        headers["User-Agent"] = random.choice(UA_POOL)
    r = SESSION.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    # 403 не поднимаем (антибот) — но не считаем «валидом» без доп.проверки
    if r.status_code != 403:
        r.raise_for_status()
    return r

def http_head(url: str, *, referer: Optional[str] = None, timeout: int = 15) -> requests.Response:
    headers: Dict[str, str] = {}
    if referer:
        headers["Referer"] = referer
    if random.random() < 0.25:
        headers["User-Agent"] = random.choice(UA_POOL)
    return SESSION.head(url, headers=headers, timeout=timeout, allow_redirects=True)

# ---------- text/slug helpers ----------
FANCY_QUOTES = dict.fromkeys(map(ord, "‘’‚‛“”„‟´`"), " ")
PUNCT_RX = re.compile(r"[^\w\s]+", re.U)

def normalize_text(s: str) -> str:
    s = (s or "").translate(FANCY_QUOTES)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("&", " ")
    s = PUNCT_RX.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def tokens(s: str) -> List[str]:
    return [t for t in normalize_text(s).split() if t]

def slugify(s: str) -> str:
    return normalize_text(s).replace(" ", "-")

def title_slug_candidates(title: str) -> List[str]:
    title = title or ""
    keep_paren = title.replace("(", " ").replace(")", " ")
    v_keep = slugify(keep_paren)  # приоритет №1 — сохраняем содержимое скобок
    v_base = slugify(title)
    no_paren = re.sub(r"\(.*?\)", " ", title)
    v_no_paren = slugify(no_paren)

    MARKERS = ["extended mix", "original mix", "edit", "remix", "radio edit", "club mix", "version"]
    def drop_markers(x: str) -> str:
        n = normalize_text(x)
        for m in MARKERS:
            n = n.replace(m, " ")
        return re.sub(r"\s+", " ", n).strip()

    v_base_nomark    = slugify(drop_markers(title))
    v_keep_nomark    = slugify(drop_markers(keep_paren))
    v_noparen_nomark = slugify(drop_markers(no_paren))

    ordered = [v_keep, v_base, v_no_paren, v_keep_nomark, v_base_nomark, v_noparen_nomark]
    seen, out = set(), []
    for v in ordered:
        if v and v not in seen:
            out.append(v); seen.add(v)
    return out

def artist_subdomain_candidates(artist: str) -> List[str]:
    norm = normalize_text(artist)
    compact = norm.replace(" ", "")
    dashed  = norm.replace(" ", "-")
    uniq: List[str] = []
    for h in [compact, dashed]:
        if h and h not in uniq:
            uniq.append(h)
    return uniq

def artist_slug_from_host(host: str) -> str:
    if not host.endswith(".bandcamp.com"):
        return ""
    sub = host[: -len(".bandcamp.com")]
    return normalize_text(sub.replace("-", " "))

# ---------- HTML extractors ----------
def looks_like_track_or_album(html_text: str) -> bool:
    soup = BS(html_text)
    return bool(soup.select_one(".trackTitle, h2.trackTitle, .trackTitle[itemprop='name']"))

def extract_canonical(html_text: str, fallback_url: str) -> str:
    soup = BS(html_text)
    og = soup.find("meta", attrs={"property": "og:url"})
    if og and og.get("content"):
        u = og["content"].strip()
        return u if u.startswith("http") else urljoin(fallback_url, u)
    link = soup.find("link", rel=lambda v: v and ("canonical" in (v if isinstance(v, list) else [v])))
    if link and link.get("href"):
        u = link["href"].strip()
        return u if u.startswith("http") else urljoin(fallback_url, u)
    return fallback_url

def extract_by_artist(html_text: str) -> str:
    soup = BS(html_text)
    for sel in [
        "#name-section h3 span a", "#name-section h3 a",
        ".byline a", ".trackTitle ~ .byline a", ".albumTitle ~ .byline a",
        ".detail-artist a"
    ]:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(" ", strip=True)
    text = soup.get_text(" ", strip=True)
    m = re.search(r"\bby\s+([^\n|]+)", text, flags=re.I)
    return m.group(1).strip() if m else ""

def extract_track_title(html_text: str) -> str:
    soup = BS(html_text)
    el = soup.select_one(".trackTitle, h2.trackTitle, .trackTitle[itemprop='name']")
    return el.get_text(" ", strip=True) if el else ""

# ---------- строгая валидация кандидата ----------
def validate_candidate(url: str, *, want_artist: str, want_title: str) -> Tuple[Optional[str], int]:
    """
    Возвращает (валидный_url, fit_score) или (None, 0).
    - Для 200: проверяем, что страница действительно «трек/альбом» и там есть совпадения
      по названию (title tokens) и артисту (byline или host).
    - Для 403: HEAD != 404 → ok (но fit_score ниже, тк контент не прочитан).
    """
    try:
        r = http_get(url, referer=BANDCAMP)
    except requests.HTTPError:
        return (None, 0)

    final_url = r.url or url

    # 200: проверяем контент
    if r.status_code == 200 and r.text:
        if not looks_like_track_or_album(r.text):
            return (None, 0)
        page_title = extract_track_title(r.text)
        by_artist  = extract_by_artist(r.text)
        # метрики совпадения
        t_want = set(tokens(want_title))
        a_want = set(tokens(want_artist))
        t_page = set(tokens(page_title))
        a_by   = set(tokens(by_artist))
        # slug страницы тоже учитываем для названия
        path_slug = set(tokens(urlparse(final_url).path.replace("/", " ").replace("-", " ")))
        title_hit = len(t_want & (t_page | path_slug))
        by_hit    = len(a_want & a_by)
        host_hit  = len(a_want & set(tokens(artist_slug_from_host(urlparse(final_url).netloc))))
        # минимальные пороги: хотя бы половина токенов названия и >=1 токен артиста (по byline или host)
        if title_hit >= max(1, len(t_want) // 2) and (by_hit > 0 or host_hit > 0):
            # взвешенный фит: название важнее, потом byline, потом host
            fit = 6*title_hit + 3*by_hit + 1*host_hit
            return (extract_canonical(r.text, final_url), fit)
        return (None, 0)

    # 403: допускаем как валидный ТОЛЬКО если не 404 по HEAD
    if r.status_code == 403:
        try:
            h = http_head(final_url, referer=BANDCAMP)
            if h.status_code != 404:
                # контент не видим → ставим скромный фит, но даём шанс как fallback
                return (final_url, 1)
        except Exception:
            pass
        return (None, 0)

    # всё остальное (включая 404) — невалид
    return (None, 0)

# ---------- парсинг результатов bandcamp.com/search ----------
def build_search_url(artist: str, title: str) -> str:
    q = f"{title} {artist}".strip()
    return f"{BANDCAMP}/search?q={quote(q)}"

def parse_search_candidates(html_text: str) -> List[Tuple[str, str, str]]:
    soup = BS(html_text)
    out: List[Tuple[str, str, str]] = []
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if not href or ".bandcamp.com/" not in href:
            continue
        if "/track/" not in href and "/album/" not in href:
            continue
        title_text = a.get_text(" ", strip=True)
        artist_el = a.find_next(class_=re.compile(r"(subhead|result-info|heading|artist)", re.I))
        artist_text = artist_el.get_text(" ", strip=True) if artist_el else ""
        out.append((href, title_text, artist_text))
    if not out:
        for a in soup.select("a[href*='.bandcamp.com/track/'], a[href*='.bandcamp.com/album/']"):
            href = a.get("href", "")
            title_text = a.get_text(" ", strip=True)
            out.append((href, title_text, ""))
    return out

def score_candidate(url: str, title_text: str, artist_text: str,
                    want_artist: str, want_title: str, kind: str) -> int:
    score = 0
    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path
    t_want = set(tokens(want_title))
    a_want = set(tokens(want_artist))
    t_text = set(tokens(title_text))
    a_text = set(tokens(artist_text))
    t_slug = set(tokens(path.replace("/", " ").replace("-", " ")))
    a_host = set(tokens(artist_slug_from_host(host)))
    # тип
    if kind == "track" and "/track/" in path: score += 10
    if kind == "album" and "/album/" in path: score += 10
    if kind == "either": score += 5
    # название — высокий вес
    score += 6 * len(t_want & t_text)
    score += 4 * len(t_want & t_slug)
    # артист в тексте результата
    score += 4 * len(a_want & a_text)
    # артист в поддомене — слабый сигнал
    score += 2 * len(a_want & a_host)
    # почти точное совпадение названия
    if t_want and t_want.issubset(t_text | t_slug):
        score += 5
    return score

def search_bandcamp(artist: str, title: str, *, kind: str, debug: bool=False) -> Optional[str]:
    # Несколько формул запроса — чтобы не упираться в разметку/антибот:
    queries = [(title, artist), (title, ""), ("", f"{title} {artist}")]
    for q_title, q_artist in queries:
        r = http_get(build_search_url(q_artist, q_title) if q_artist else build_search_url("", q_title),
                     referer=BANDCAMP)
        if debug and r.status_code == 403:
            print("[search] 403 — парсим HTML как есть.")
        cands = parse_search_candidates(r.text)
        if debug: print(f"[search] '{q_title} {q_artist}' → кандидатов: {len(cands)}")
        if not cands:
            continue

        scored: List[Tuple[int, str]] = []
        for href, t_text, a_text in cands:
            abs_url = href if href.startswith("http") else urljoin(BANDCAMP, href)
            scored.append((score_candidate(abs_url, t_text, a_text, artist, title, kind), abs_url))
        scored.sort(key=lambda x: x[0], reverse=True)

        best_url, best_fit = None, -1
        for sc, cand in scored[:15]:
            if debug: print(f"[check] {sc:3d} {cand}")
            valid, fit = validate_candidate(cand, want_artist=artist, want_title=title)
            if not valid:
                continue
            # лёгкий early-exit: если совпали >= половины title-токенов и есть by/host, fit уже высокий
            if fit >= 10:
                return valid
            if fit > best_fit:
                best_fit, best_url = fit, valid

        if best_url:
            return best_url
    return None

# ---------- fallback: осторожные slug-и на поддоменах артиста ----------
def fallback_probe_slugs(artist: str, title: str, *, kind: str, debug: bool=False) -> Optional[str]:
    hosts = artist_subdomain_candidates(artist)
    slugs = title_slug_candidates(title)
    paths: List[str] = []
    if kind in ("track", "either"):
        paths += [f"/track/{s}" for s in slugs]
    if kind in ("album", "either"):
        paths += [f"/album/{s}" for s in slugs]

    for h in hosts:
        base = f"https://{h}.bandcamp.com"
        for p in paths:
            cand = base + p
            valid, fit = validate_candidate(cand, want_artist=artist, want_title=title)
            if valid:
                if debug: print(f"[probe] HIT fit={fit} {valid}")
                return valid
        time.sleep(0.15)
    return None

# ---------- public API ----------
def find_on_bandcamp(artist: str, title: str, *, kind: str = "either", debug: bool=False) -> Optional[str]:
    url = search_bandcamp(artist, title, kind=kind, debug=debug)
    if url:
        return url
    url = fallback_probe_slugs(artist, title, kind=kind, debug=debug)
    if url:
        return url
    return None

# ---------- CLI ----------
def main():
    ap = argparse.ArgumentParser(description="Надёжный поиск страницы трека/альбома на bandcamp.com")
    ap.add_argument("--artist", required=True, help="Исполнитель/перформер или проект/лейбл")
    ap.add_argument("--title", required=True, help="Название композиции/релиза")
    ap.add_argument("--kind", choices=["track", "album", "either"], default="either", help="Ограничить тип")
    ap.add_argument("--debug", action="store_true", help="Диагностические сообщения")
    args = ap.parse_args()

    url = find_on_bandcamp(args.artist, args.title, kind=args.kind, debug=args.debug)
    print(url or "NOT FOUND")

if __name__ == "__main__":
    main()
