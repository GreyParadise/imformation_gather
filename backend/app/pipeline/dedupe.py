import hashlib
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

TRACKING_PREFIXES = ("utm_", "spm_", "from=", "share_")
TRACKING_EXACT = {"gclid", "gs_l", "fbclid", "twclid", "msclkid", "v", "dfp", "tda", "ig", "scid", "scene", "transparent_key"}


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    scheme = parts.scheme.lower() or "https"
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+$", "", parts.path) or "/"
    query = []
    for k, v in parse_qsl(parts.query, keep_blank_values=False):
        kl = k.lower()
        if kl in TRACKING_EXACT or kl.startswith(TRACKING_PREFIXES):
            continue
        query.append((kl, v))
    return urlunsplit((scheme, host, path, urlencode(sorted(query)), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:32]


_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


def _tokens(text: str):
    text = (text or "").lower()
    words = _TOKEN_RE.findall(text)
    tokens = []
    for w in words:
        if len(w) == 1 and "\u4e00" <= w <= "\u9fff":
            tokens.append(w)
        else:
            tokens.append(w)
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    for a, b in zip(cjk, cjk[1:]):
        tokens.append(a + b)
    return tokens


def _token_hash64(token: str) -> int:
    h = hashlib.md5(token.encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big")


def simhash64(text: str) -> int:
    tokens = _tokens(text)
    if not tokens:
        return 0
    vec = [0] * 64
    for t in tokens:
        h = _token_hash64(t)
        for i in range(64):
            vec[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(64):
        if vec[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    x = (a or 0) ^ (b or 0)
    return bin(x).count("1")
