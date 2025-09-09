import re
from typing import List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

def canonical_noquery(u: str) -> str:
    sp = urlsplit(u)
    return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))

def normalize_text(s: str) -> str:
    s = (s or "").lower().replace("’", "'").replace("‘", "'").replace("`", "'")
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def slugify_simple(s: str) -> str:
    s = normalize_text(s)
    s = re.sub(r"[^\w\s-]+", " ", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s

def title_slug_candidates(title: str) -> List[str]:
    t = title or ""
    v1 = slugify_simple(t)
    v2 = slugify_simple(t.replace("'", ""))           # Jacob's → Jacobs
    v3 = slugify_simple(re.sub(r"\(.*?\)", " ", t))   # без скобок
    MARKERS = r"(extended mix|original mix|edit|remix|radio edit|version|club mix|feat|ft)"
    v4 = slugify_simple(re.sub(MARKERS, " ", normalize_text(t)))
    out, seen = [], set()
    for v in (v1, v2, v3, v4):
        if v and v not in seen:
            seen.add(v); out.append(v)
    return out

def link_score(u: str, artist: str, title: str) -> Tuple[int, str]:
    can = canonical_noquery(u)
    m = re.search(r"/track/([^/?#]+)", can)
    slug = (m.group(1).lower() if m else "")

    want_slugs = set(title_slug_candidates(title))
    score = 0
    if slug in want_slugs:
        score += 100

    slug_tokens = set(re.findall(r"\w+", slug.replace("-", " ")))
    title_tokens = set(re.findall(r"\w+", normalize_text(title)))
    score += 10 * len(slug_tokens & title_tokens)

    host = urlsplit(can).netloc
    if host.endswith(".bandcamp.com"):
        sub = host[:-len(".bandcamp.com")].replace("-", " ")
        if set(re.findall(r"\w+", normalize_text(artist))) & set(re.findall(r"\w+", sub)):
            score += 5

    return score, can

def pick_best_link(links: List[str], artist: str, title: str) -> Optional[str]:
    best_url, best_sc = None, -1
    for u in links:
        if "/track/" not in u:
            continue
        sc, can = link_score(u, artist, title)
        if sc > best_sc:
            best_sc, best_url = sc, can
    return best_url
