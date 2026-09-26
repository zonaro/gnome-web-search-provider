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
import sys
import urllib.parse
import urllib.request

CACHE_DIR_NAME = "gnome-web-search-provider"
FAVICONS_DIR_NAME = "favicons"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) gnome-web-search-provider/1.0"
TIMEOUT = 8
MAX_WORKERS = 8
MIN_BYTES = 100
MAX_BYTES = 2 * 1024 * 1024

# Extensions we accept from the cache (checked in this order).
_CACHED_EXTENSIONS = (".png", ".ico", ".svg", ".jpg", ".jpeg", ".webp")

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
        f"https://{domain}/favicon.ico",
    ]


# Some providers live on subdomains/paths that do not serve a favicon at
# the conventional location; map them to the brand domain that does.
_DOMAIN_OVERRIDES = {
    "brave": "brave.com",
    "brave-images": "brave.com",
    "yep": "ahrefs.com",
    "google-news": "www.google.com",
    "fonts": "www.google.com",
    "hackernews": "ycombinator.com",
    "wolframalpha": "wolfram.com",
    "dockerhub": "docker.com",
}


def icon_domain(provider_id: str, search_url: str) -> str:
    return _DOMAIN_OVERRIDES.get(provider_id, domain_for_provider(search_url))


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
            content_type = response.headers.get_content_type() if hasattr(response.headers, "get_content_type") else ""
            if content_type and "image" not in content_type:
                return None
            body = response.read(MAX_BYTES + 1)
    except Exception:
        return None
    if not body or len(body) < MIN_BYTES or len(body) > MAX_BYTES:
        return None
    return body, content_type or ""


def fetch_favicon(provider_id: str, search_url: str, timeout: int = TIMEOUT) -> str | None:
    """Download the site icon for one provider into the cache.

    Returns the saved file path, the existing cached path when the
    network fails but a cache entry exists, or None.
    """
    domain = icon_domain(provider_id, search_url)
    if not domain:
        return cached_icon_path(provider_id)
    directory = cache_dir()
    safe_id = "".join(c for c in provider_id if c.isalnum() or c in ("-", "_")) or "icon"
    for url in favicon_candidates(domain):
        result = _download(url, timeout)
        if result is None:
            continue
        body, content_type = result
        ext = extension_for(content_type, url)
        # Remove stale variants so cached_icon_path() finds the fresh file.
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
    from .providers import PROVIDERS

    return ensure_favicons(
        {pid: p.url for pid, p in PROVIDERS.items()},
        force=force,
    )


def main(argv: list | None = None) -> int:
    force = "--force" in (argv or sys.argv[1:])
    results = prefetch_all(force=force)
    ok = sum(1 for path in results.values() if path)
    print(f"favicons: {ok}/{len(results)} cached")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
