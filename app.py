import argparse
import os
import sys

from src.bc_search_engine.app_bc_search import find_on_bandcamp
from src.track_downloader import download_file
from src.track_link_url import get_track_download_link

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def main(args):
    track_page_url = find_on_bandcamp(args.artist, args.title)
    if track_page_url:
        print("Страница трека:", track_page_url)
    else:
        print("NOT FOUND")
        return

    track_link = get_track_download_link(track_page_url, timeout_sec=60)
    print(f"Ссылка на скачивание: {track_link}")

    if track_link is None:
        raise SystemExit(4)

    download_file(track_link, "track.mp3")
    print("Трек сохранён как track.mp3")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Поиск страницы трека на bandcamp.com")
    ap.add_argument("--artist", required=True, help="Имя исполнителя, напр.: 'DJ Pantelis'")
    ap.add_argument("--title", required=True,
                    help="Название трека, напр.: 'DJ Pantelis & Geo Spiropoulos - Thelo Na Me Nioseis (Extended Mix)'")
    ap.add_argument("--debug", action="store_true", help="Диагностические сообщения")
    arguments = ap.parse_args()

    main(arguments)
