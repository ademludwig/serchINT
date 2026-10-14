import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def strip_accents(text):
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_text(text):
    """Case/accent/whitespace-insensitive form used for matching."""
    return " ".join(strip_accents(text).casefold().split())


def normalize_url(url):
    """Canonical URL for deduplication (no fragment, no utm_*, no trailing slash)."""
    parts = urlsplit(url.strip())
    query = sorted((k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_"))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))
