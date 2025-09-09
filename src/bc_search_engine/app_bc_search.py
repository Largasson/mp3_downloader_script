# -*- coding: utf-8 -*-
"""
Bandcamp track finder (browser-only).

Публичный контракт:
    find_on_bandcamp(artist: str, title: str, log_level: int | str = "INFO") -> Optional[str]
Возвращает канонический BEST-URL страницы трека на Bandcamp или None.

Как работает:
  - строит URL поиска с фильтром tracks (&item_type=t),
  - открывает его headless-браузером (Playwright),
  - собирает все href'ы /track/... с первой страницы,
  - выбирает лучший по URL-слугу и возвращает канонический URL (без query).

Логи: стандартный logging (stderr). По умолчанию INFO; можно передать другой уровень.
stdout CLI печатает ТОЛЬКО итог (BEST-URL | NOT FOUND).
"""

import logging
from typing import Optional, Union
from urllib.parse import quote_plus

from config.settings import get_logger
from .playwright_fetch import fetch_links_via_playwright
from .scoring import pick_best_link


def _resolve_log_level(level: Union[int, str]) -> int:
    """Преобразует строковый уровень ('DEBUG', 'INFO', ...) или int в valid logging level."""
    if isinstance(level, int):
        return level
    name = (level or "").upper()
    return getattr(logging, name, logging.INFO)


def build_bandcamp_search_url(artist: str, title: str) -> str:
    """Собирает URL страницы поиска Bandcamp для треков (item_type=t)."""
    q = " ".join([p for p in [title, artist] if p]).strip()
    url = f"https://bandcamp.com/search?q={quote_plus(q)}&item_type=t"
    return url


def find_on_bandcamp(
        artist: str,
        title: str,
        log_level: Union[int, str] = logging.INFO,
) -> Optional[str]:
    """
    Ищет страницу трека Bandcamp по артисту и названию и возвращает BEST-URL или None.

    :param artist: Имя артиста.
    :param title:  Название трека.
    :param log_level: Уровень логирования (int или 'DEBUG'/'INFO'/...).
    :return: Канонический URL вида https://<host>.bandcamp.com/track/<slug> или None.
    """
    logger = get_logger()
    logger.setLevel(_resolve_log_level(log_level))

    search_url = build_bandcamp_search_url(artist, title)
    logger.debug("search URL: %s", search_url)

    # Браузер: читаем реальный DOM с /search?item_type=t
    links = fetch_links_via_playwright(search_url, logger=logger)
    logger.info("[playwright] parsed links: %d", len(links))

    if not links:
        logger.warning("No candidates collected")
        return None

    best = pick_best_link(links, artist, title)
    if best:
        logger.info("BEST: %s", best)
        return best

    logger.warning("No BEST link among %d candidates", len(links))
    return None


# -------- CLI ----------
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Bandcamp BEST link finder (stdout: BEST or NOT FOUND)")
    ap.add_argument("--artist", help="Имя артиста")
    ap.add_argument("--title", help="Название трека")
    ap.add_argument("--log-level", default="INFO", help="DEBUG | INFO | WARNING | ERROR | CRITICAL (по умолчанию INFO)")
    args = ap.parse_args()

    # Интерактивный ввод, если аргументы не переданы (удобно при запуске из IDE)
    artist = args.artist or input("Artist: ").strip()
    title = args.title or input("Title : ").strip()

    best = find_on_bandcamp(artist=artist, title=title, log_level=args.log_level)
    print(best or "NOT FOUND")
