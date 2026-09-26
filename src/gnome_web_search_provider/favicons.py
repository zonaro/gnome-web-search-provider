"""Favicon fetching + disk cache for provider icons.

Each search provider gets its real site icon (downloaded from the site
itself), with the bundled symbolic icons used as fallback while the
download is pending or when it fails (offline, site without favicon, ...).

Only the Python standard library is used here so this module also works
outside the GTK app (e.g. during install for a best-effort prefetch)::

    python3 -m gnome_web_search_provider.favicons [--force]
"""

import concurrent.futures
import os
import re
import sys
import urllib.parse
import urllib.request

CACHE_DIR_NAME = "gnome-web-search-provider"
FAVICONS_DIR_NAME = "favicons"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) "
    "Gecko/20100101 Firefox/121.0 gnome-web-search-provider/1.0"
)
TIMEOUT = 8
MAX_WORKERS = 8
MIN_BYTES = 100
MAX_BYTES = 2 * 1024 * 1024
HTML_MAX_BYTES = 256 * 1024

# Extensions we accept from the cache (checked in this order).
_CACHED_EXTENSIONS = (".png", ".ico", ".svg", ".jpg", ".jpeg", ".webp", ".gif")

_CONTENT_TYPE_EXT = {
    "image/png": ".png",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
    "image/svg+xml": ".svg",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def cache_dir() -> str:
    """Return the favicon cache dir, creating it on demand."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    path = os.path.join(base, CACHE_DIR_NAME, FAVICONS_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def domain_for_provider(search_url: str) -> str:
    """Extract the host (e.g. ``www.google.com``) from a provider search URL."""
    return urllib.parse.urlparse(search_url).netloc.lower()


def favicon_candidates(domain: str) -> list:
    """Ordered favicon URLs to try for ``domain`` (crisp first)."""
    domain = domain.strip().lower().strip("/")
    if not domain:
        return []
    return [
        f"https://{domain}/apple-touch-icon.png",
        f"https://{domain}/apple-touch-icon-precomposed.png",
        f"https://{domain}/favicon.png",
        f"https://{domain}/favicon.ico",
    ]


def external_favicon_fallbacks(domain: str) -> list:
    """Third-party icon services used as last resort for ``domain``.

    ``google/s2`` and DuckDuckGo's ``ip3`` render the site's own icon
    for virtually any domain, including ones that block direct fetches
    (403) or serve the icon from hashed/bundled paths.
    """
    domain = (domain or "").strip().lower().strip("/")
    if not domain:
        return []
    return [
        f"https://www.google.com/s2/favicons?domain={domain}&sz=128",
        f"https://icons.duckduckgo.com/ip3/{domain}.ico",
    ]


_LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_REL_ICON_RE = re.compile(r"""rel\s*=\s*["'][^"']*icon[^"']*["']""", re.IGNORECASE)
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_SIZES_RE = re.compile(r"""sizes\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_SIZE_NUM_RE = re.compile(r"(\d+)\s*[x×]\s*(\d+)")


def _icon_link_size(tag: str) -> int:
    """Largest width declared in a ``sizes`` attribute (0 when absent)."""
    match = _SIZES_RE.search(tag)
    if not match:
        return 0
    best = 0
    for w, _h in _SIZE_NUM_RE.findall(match.group(1)):
        try:
            best = max(best, int(w))
        except ValueError:
            continue
    return best


def parse_icon_links(html: str, base_url: str) -> list:
    """Extract ``<link rel=*icon*>`` hrefs from ``html`` as absolute URLs.

    Ordered biggest-first (crisp icons win); ``any``/SVG entries keep
    their document order after sized PNGs.
    """
    found: list = []
    seen = set()
    scored: list = []
    try:
        tags = _LINK_TAG_RE.findall(html or "")
    except Exception:
        return []
    for tag in tags:
        if not _REL_ICON_RE.search(tag):
            continue
        match = _HREF_RE.search(tag)
        if not match:
            continue
        href = match.group(1).strip()
        if not href or href.startswith(("data:", "blob:", "javascript:")):
            continue
        try:
            absolute = urllib.parse.urljoin(base_url, href)
        except Exception:
            continue
        if not absolute.startswith(("http://", "https://")):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        scored.append((_icon_link_size(tag), len(found), absolute))
        found.append(absolute)
    # Biggest first; keep document order as tiebreak.
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [url for _, _, url in scored]


def discover_icon_links(domain: str, timeout: int = TIMEOUT) -> list:
    """Fetch ``https://{domain}/`` and return its declared icon URLs."""
    domain = (domain or "").strip().lower().strip("/")
    if not domain:
        return []
    base_url = f"https://{domain}/"
    request = urllib.request.Request(
        base_url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if getattr(response, "status", 200) not in (200, None):
                return []
            raw = response.read(HTML_MAX_BYTES + 1)
    except Exception:
        return []
    if not raw:
        return []
    try:
        html = raw.decode("utf-8", "ignore")
    except Exception:
        return []
    if "<link" not in html.lower():
        return []
    return parse_icon_links(html, base_url)


# Providers whose search URL lives on a subdomain/path without its own
# icon: extra brand domains tried (after the real search domain).
_DOMAIN_OVERRIDES = {
    "brave": "brave.com",
    "brave-images": "brave.com",
    "yep": "ahrefs.com",
    "hackernews": "news.ycombinator.com",
    "dockerhub": "docker.com",
    "tidal": "tidal.com",
    "youtube-music": "youtube.com",
    "spotify": "spotify.com",
    "mdn": "mozilla.org",
    "archwiki": "archlinux.org",
    # Google verticals share the Google brand icon.
    "google-news": "www.google.com",
    "google-scholar": "scholar.google.com",
    "translate": "translate.google.com",
    "fonts": "fonts.google.com",
}


def icon_domains(provider_id: str, search_url: str) -> list:
    """Ordered domains to try for ``provider_id`` (real domain first)."""
    domains: list = []
    primary = domain_for_provider(search_url)
    if primary:
        domains.append(primary)
    fallback = _DOMAIN_OVERRIDES.get(provider_id)
    if fallback and fallback not in domains:
        domains.append(fallback)
    # Google verticals without an explicit entry still fall back to Google.
    if not fallback and provider_id in (
        "google-images",
        "google-videos",
        "google-maps",
        "flights",
    ):
        if "www.google.com" not in domains:
            domains.append("www.google.com")
    return domains


def icon_domain(provider_id: str, search_url: str) -> str:
    domains = icon_domains(provider_id, search_url)
    for domain in domains:
        if domain == _DOMAIN_OVERRIDES.get(provider_id):
            return domain
    return domains[0] if domains else ""


def cached_icon_path(provider_id: str) -> str | None:
    try:
        directory = cache_dir()
    except OSError:
        return None
    for ext in _CACHED_EXTENSIONS:
        path = os.path.join(directory, f"{provider_id}{ext}")
        try:
            if os.path.getsize(path) >= MIN_BYTES:
                return path
        except OSError:
            continue
    return None


def extension_for(content_type: str, url: str) -> str:
    """Map an HTTP content-type (falling back to the URL suffix) to a file ext."""
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in _CONTENT_TYPE_EXT:
        return _CONTENT_TYPE_EXT[ctype]
    suffix = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if suffix in _CACHED_EXTENSIONS or suffix == ".gif":
        return suffix
    return ".png"


def _looks_like_image(body: bytes, content_type: str, url: str) -> bool:
    if not body:
        return False
    lowered = (content_type or "").split(";")[0].strip().lower()
    if lowered.startswith("image/"):
        return True
    # Some hosts serve a valid icon as application/octet-stream (or omit
    # the header); validate by magic bytes instead of trusting the type.
    if lowered in ("application/octet-stream", "binary/octet-stream", ""):
        head = body[:16]
        if head.startswith((b"\x89PNG", b"GIF87a", b"GIF89a", b"\xff\xd8\xff")):
            return True
        if head.startswith(b"RIFF") and b"WEBP" in body[:32]:
            return True
        if head.startswith((b"\x00\x00\x01\x00", b"\x00\x00\x02\x00")):
            return True  # .ico
        stripped = body.lstrip()[:256].lower()
        if stripped.startswith(b"<svg") or b"<svg" in stripped[:128]:
            return True
        suffix = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
        if suffix in _CACHED_EXTENSIONS:
            return True
        return False
    if "image" in lowered:
        return True
    return False


def _download(url: str, timeout: int) -> tuple[bytes, str] | None:
    """Fetch ``url``; return ``(body, content_type)`` for real images, else None."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*;q=0.8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if getattr(response, "status", 200) not in (200, None):
                return None
            headers = getattr(response, "headers", None)
            try:
                content_type = headers.get_content_type() if hasattr(headers, "get_content_type") else headers.get("Content-Type", "")
            except Exception:
                content_type = ""
            body = response.read(MAX_BYTES + 1)
    except Exception:
        return None
    if not body or len(body) < MIN_BYTES or len(body) > MAX_BYTES:
        return None
    if not _looks_like_image(body, content_type or "", url):
        return None
    return body, content_type or ""


def _save_body(provider_id: str, directory: str, body: bytes, content_type: str, url: str) -> str | None:
    safe_id = "".join(c for c in provider_id if c.isalnum() or c in ("-", "_")) or "icon"
    ext = extension_for(content_type, url)
    for old_ext in _CACHED_EXTENSIONS:
        if old_ext != ext:
            try:
                os.remove(os.path.join(directory, f"{safe_id}{old_ext}"))
            except OSError:
                pass
    path = os.path.join(directory, f"{safe_id}{ext}")
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "wb") as fh:
            fh.write(body)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return cached_icon_path(provider_id)
    return path


def _try_urls(urls: list, directory: str, provider_id: str, timeout: int) -> str | None:
    for url in urls:
        result = _download(url, timeout)
        if result is None:
            continue
        body, content_type = result
        return _save_body(provider_id, directory, body, content_type, url)
    return None


def fetch_favicon(provider_id: str, search_url: str, timeout: int = TIMEOUT) -> str | None:
    """Download the site icon for one provider into the cache.

    Tries, per domain: conventional paths, then the page's
    ``<link rel=icon>`` targets, then Google-S2/DuckDuckGo fallbacks.
    Returns the saved file path, the existing cached path when the
    network fails but a cache entry exists, or None.
    """
    domains = icon_domains(provider_id, search_url)
    if not domains:
        return cached_icon_path(provider_id)
    directory = cache_dir()
    for domain in domains:
        found = _try_urls(favicon_candidates(domain), directory, provider_id, timeout)
        if found:
            return found
        try:
            declared = discover_icon_links(domain, timeout)
        except Exception:
            declared = []
        if declared:
            found = _try_urls(declared, directory, provider_id, timeout)
            if found:
                return found
    for domain in domains:
        found = _try_urls(external_favicon_fallbacks(domain), directory, provider_id, timeout)
        if found:
            return found
    return cached_icon_path(provider_id)


def ensure_favicons(
    providers: dict,
    force: bool = False,
    timeout: int = TIMEOUT,
    max_workers: int = MAX_WORKERS,
) -> dict:
    """Fetch icons for ``{provider_id: search_url}`` in parallel.

    Already-cached providers are skipped unless ``force`` is True.
    Never raises: failures map to None (caller keeps the fallback icon).
    """
    pending = {}
    results: dict = {}
    for provider_id, search_url in providers.items():
        if not force:
            cached = cached_icon_path(provider_id)
            if cached:
                results[provider_id] = cached
                continue
        pending[provider_id] = search_url
    if not pending:
        return results

    def _one(item) -> tuple:
        provider_id, search_url = item
        try:
            return provider_id, fetch_favicon(provider_id, search_url, timeout)
        except Exception:
            return provider_id, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        for provider_id, path in pool.map(_one, pending.items()):
            results[provider_id] = path
    return results


def prefetch_all(force: bool = False) -> dict:
    """Fetch icons for every registered provider; used by installers."""
    from .providers import PROVIDERS, custom_providers_from_list

    urls = {pid: p.url for pid, p in PROVIDERS.items()}
    try:
        from .config import ConfigManager

        customs = custom_providers_from_list(ConfigManager(use_gsettings=False).get_custom_providers())
        for pid, provider in customs.items():
            urls[pid] = provider.url
    except Exception:
        pass
    return ensure_favicons(urls, force=force)


def main(argv: list | None = None) -> int:
    force = "--force" in (argv or sys.argv[1:])
    results = prefetch_all(force=force)
    ok = sum(1 for path in results.values() if path)
    print(f"favicons: {ok}/{len(results)} cached")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
