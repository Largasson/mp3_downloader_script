import random
from typing import Dict, Optional

import requests
from requests.adapters import HTTPAdapter, Retry

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
]


def make_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
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


def http_get(url: str, params: Optional[Dict[str, str]] = None, *, timeout: int = 20,
             referer: Optional[str] = None) -> requests.Response:
    headers = {}
    if referer:
        headers["Referer"] = referer
    if random.random() < 0.25:
        headers["User-Agent"] = random.choice(UA_POOL)
    resp = SESSION.get(url, params=params, headers=headers, timeout=timeout)
    # На 403 не бросаем, чтобы дать шанс fallback-логике
    if resp.status_code != 403:
        resp.raise_for_status()
    return resp


def download_file(url: str, dest_path: str) -> None:
    r = http_get(url)
    r.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(r.content)


if __name__ == "__main__":
    test_link_url = 'https://t4.bcbits.com/stream/f27449aef08dfcadddb8be4cd9ffae2b/mp3-128/2798952427?p=0&ts=1756900375&t=42cd35ddccafb9f0a642c36897cde23e0a3dbd83&token=1756900375_cf59c7275f9ccaec275c19d45305d9584a8e0a3b'
    download_file(test_link_url, "track.mp3")
