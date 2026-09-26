"""Registry of web search providers.

Every provider builds its search URL from a template with a ``{query}``
placeholder. Query strings are URL-encoded with ``quote_plus`` (spaces
become ``+``); providers that take the query in the URL *path* (e.g.
Google Maps) use ``quote`` instead (spaces become ``%20``).

URLs were verified in 2026 (HTTP checks + redirect inspection):

* Google now prefers ``udm=`` over ``tbm=`` for verticals: images
  ``udm=2``, videos ``udm=vids``.
* Marginalia moved to ``marginalia-search.com``.
* Kagi and You.com are included (requested in upstream issue #1): Kagi
  shows a sign-in wall for anonymous searches (it needs a paid Kagi
  account), You.com works anonymously. Both rely on the browser session.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from urllib.parse import quote, quote_plus

DEFAULT_ICON = "web-browser"

# Themed fallback icon per category (all verified against Adwaita).
CATEGORY_ICONS: Dict[str, str] = {
    "web": "web-browser-symbolic",
    "images": "image-x-generic-symbolic",
    "maps": "mark-location-symbolic",
    "google-services": "system-search-symbolic",
    "community": "system-users-symbolic",
    "media": "multimedia-player-symbolic",
    "reference": "help-browser-symbolic",
}

# Distinctive fallback icons for a few providers (Adwaita names).
PROVIDER_ICONS: Dict[str, str] = {
    "google-maps": "find-location-symbolic",
    "bing-maps": "find-location-symbolic",
    "openstreetmap": "find-location-symbolic",
    "google-images": "folder-pictures-symbolic",
    "bing-images": "folder-pictures-symbolic",
    "duckduckgo-images": "folder-pictures-symbolic",
    "brave-images": "folder-pictures-symbolic",
    "startpage-images": "folder-pictures-symbolic",
    "youtube": "video-x-generic-symbolic",
    "google-videos": "video-x-generic-symbolic",
    "spotify": "audio-x-generic-symbolic",
    "youtube-music": "audio-x-generic-symbolic",
    "deezer": "audio-x-generic-symbolic",
    "tidal": "audio-x-generic-symbolic",
    "flights": "airplane-mode-symbolic",
    "fonts": "font-x-generic-symbolic",
    "translate": "accessories-dictionary-symbolic",
    "wiktionary": "accessories-dictionary-symbolic",
    "wikipedia": "help-browser-symbolic",
    "mdn": "text-x-generic-symbolic",
    "archwiki": "text-x-generic-symbolic",
    "pypi": "application-x-executable-symbolic",
    "github": "application-x-executable-symbolic",
    "dockerhub": "application-x-executable-symbolic",
    "stackoverflow": "application-x-executable-symbolic",
    "hackernews": "application-x-executable-symbolic",
    "wolframalpha": "applications-science-symbolic",
}


def fallback_icon_name(provider_id: str) -> str:
    """Themed icon name for ``provider_id`` when no favicon is cached."""
    if provider_id in PROVIDER_ICONS:
        return PROVIDER_ICONS[provider_id]
    provider = PROVIDERS.get(provider_id)
    if provider is not None and provider.category in CATEGORY_ICONS:
        return CATEGORY_ICONS[provider.category]
    if provider is not None and provider.icon:
        return provider.icon
    return "web-browser-symbolic"


@dataclass(frozen=True)
class SearchProvider:
    provider_id: str
    name: str
    url: str
    category: str
    icon: str = DEFAULT_ICON
    query_in_path: bool = field(default=False, repr=False)

    def build_url(self, query: str) -> str:
        """Return the full search URL for ``query``, properly encoded."""
        encoded = quote(query, safe="") if self.query_in_path else quote_plus(query)
        return self.url.format(query=encoded)


def _p(
    provider_id: str,
    name: str,
    url: str,
    category: str,
    query_in_path: bool = False,
) -> SearchProvider:
    return SearchProvider(
        provider_id=provider_id,
        name=name,
        url=url,
        category=category,
        query_in_path=query_in_path,
    )


# Ordered category list, used by the preferences window: (id, display label).
# Labels below stay in English for backwards compatibility; use
# ``get_category_label()`` to render them in the user's language.
CATEGORIES: List[Tuple[str, str]] = [
    ("web", "Web Search"),
    ("images", "Images"),
    ("maps", "Maps"),
    ("google-services", "Google Services"),
    ("community", "Communities & Forums"),
    ("media", "Media & Entertainment"),
    ("reference", "Reference & Tech Docs"),
]

PROVIDERS: Dict[str, SearchProvider] = {
    # ------------------------------------------------------------ Web search
    "google": _p("google", "Google", "https://www.google.com/search?q={query}", "web"),
    "bing": _p("bing", "Bing", "https://www.bing.com/search?q={query}", "web"),
    "duckduckgo": _p("duckduckgo", "DuckDuckGo", "https://duckduckgo.com/?q={query}", "web"),
    "brave": _p("brave", "Brave Search", "https://search.brave.com/search?q={query}", "web"),
    "startpage": _p("startpage", "Startpage", "https://www.startpage.com/sp/search?query={query}", "web"),
    "ecosia": _p("ecosia", "Ecosia", "https://www.ecosia.org/search?q={query}", "web"),
    "qwant": _p("qwant", "Qwant", "https://www.qwant.com/?q={query}", "web"),
    "yahoo": _p("yahoo", "Yahoo", "https://search.yahoo.com/search?p={query}", "web"),
    "mojeek": _p("mojeek", "Mojeek", "https://www.mojeek.com/search?q={query}", "web"),
    "yandex": _p("yandex", "Yandex", "https://yandex.com/search/?text={query}", "web"),
    "baidu": _p("baidu", "Baidu", "https://www.baidu.com/s?wd={query}", "web"),
    "naver": _p("naver", "Naver", "https://search.naver.com/search.naver?query={query}", "web"),
    "searxng": _p("searxng", "SearXNG", "https://searx.be/search?q={query}", "web"),
    "yep": _p("yep", "Yep (Ahrefs)", "https://yep.com/search?q={query}", "web"),
    "swisscows": _p("swisscows", "Swisscows", "https://swisscows.com/web?query={query}", "web"),
    "marginalia": _p("marginalia", "Marginalia", "https://marginalia-search.com/search?query={query}", "web"),
    "perplexity": _p("perplexity", "Perplexity", "https://www.perplexity.ai/search?q={query}", "web"),
    "kagi": _p("kagi", "Kagi", "https://kagi.com/search?q={query}", "web"),
    "you": _p("you", "You.com", "https://you.com/search?q={query}", "web"),
    # ----------------------------------------------------------------- Images
    "google-images": _p("google-images", "Google Images", "https://www.google.com/search?udm=2&q={query}", "images"),
    "bing-images": _p("bing-images", "Bing Images", "https://www.bing.com/images/search?q={query}", "images"),
    "duckduckgo-images": _p(
        "duckduckgo-images",
        "DuckDuckGo Images",
        "https://duckduckgo.com/?q={query}&iax=images&ia=images",
        "images",
    ),
    "brave-images": _p("brave-images", "Brave Images", "https://search.brave.com/images?q={query}", "images"),
    "startpage-images": _p(
        "startpage-images",
        "Startpage Images",
        "https://www.startpage.com/sp/search?query={query}&cat=pics",
        "images",
    ),
    # ------------------------------------------------------------------ Maps
    "google-maps": _p("google-maps", "Google Maps", "https://www.google.com/maps/search/{query}", "maps", query_in_path=True),
    "bing-maps": _p("bing-maps", "Bing Maps", "https://www.bing.com/maps?q={query}", "maps"),
    "openstreetmap": _p("openstreetmap", "OpenStreetMap", "https://www.openstreetmap.org/search?query={query}", "maps"),
    # -------------------------------------------------------- Google services
    "google-news": _p("google-news", "Google News", "https://news.google.com/search?q={query}", "google-services"),
    "google-scholar": _p("google-scholar", "Google Scholar", "https://scholar.google.com/scholar?q={query}", "google-services"),
    "google-videos": _p("google-videos", "Google Videos", "https://www.google.com/search?udm=vids&q={query}", "google-services"),
    "translate": _p("translate", "Google Translate", "https://translate.google.com/?sl=auto&tl=pt&text={query}", "google-services"),
    "flights": _p("flights", "Google Flights", "https://www.google.com/travel/flights?q={query}", "google-services"),
    "fonts": _p("fonts", "Google Fonts", "https://fonts.google.com/?query={query}", "google-services"),
    # ------------------------------------------------- Communities & forums
    "reddit": _p("reddit", "Reddit", "https://www.reddit.com/search/?q={query}", "community"),
    "hackernews": _p("hackernews", "Hacker News", "https://hn.algolia.com/?q={query}", "community"),
    "github": _p("github", "GitHub", "https://github.com/search?q={query}", "community"),
    "stackoverflow": _p("stackoverflow", "Stack Overflow", "https://stackoverflow.com/search?q={query}", "community"),
    # ---------------------------------------------------- Media & entertainment
    "youtube": _p("youtube", "YouTube", "https://www.youtube.com/results?search_query={query}", "media"),
    "youtube-music": _p("youtube-music", "YouTube Music", "https://music.youtube.com/search?q={query}", "media"),
    "spotify": _p("spotify", "Spotify", "https://open.spotify.com/search/{query}", "media", query_in_path=True),
    "deezer": _p("deezer", "Deezer", "https://www.deezer.com/search/{query}", "media", query_in_path=True),
    "tidal": _p("tidal", "Tidal", "https://listen.tidal.com/search?q={query}", "media"),
    "imdb": _p("imdb", "IMDb", "https://www.imdb.com/find/?q={query}", "media"),
    "steam": _p("steam", "Steam", "https://store.steampowered.com/search/?term={query}", "media"),
    # ---------------------------------------------------- Reference & tech docs
    "wikipedia": _p("wikipedia", "Wikipedia", "https://en.wikipedia.org/wiki/Special:Search?search={query}", "reference"),
    "wiktionary": _p("wiktionary", "Wiktionary", "https://en.wiktionary.org/wiki/Special:Search?search={query}", "reference"),
    "wolframalpha": _p("wolframalpha", "WolframAlpha", "https://www.wolframalpha.com/input?i={query}", "reference"),
    "pypi": _p("pypi", "PyPI", "https://pypi.org/search/?q={query}", "reference"),
    "mdn": _p("mdn", "MDN Web Docs", "https://developer.mozilla.org/en-US/search?q={query}", "reference"),
    "dockerhub": _p("dockerhub", "Docker Hub", "https://hub.docker.com/search?q={query}", "reference"),
    "archive": _p("archive", "Internet Archive", "https://archive.org/search?query={query}", "reference"),
    "archwiki": _p("archwiki", "Arch Wiki", "https://wiki.archlinux.org/index.php?search={query}", "reference"),
}

# Keep the id that must be enabled by default in sync with the GSettings
# schema default and the JSON backend default.
DEFAULT_PROVIDER_ID = "google"

_CATEGORY_TR_KEYS = {
    "web": "cat_web",
    "images": "cat_images",
    "maps": "cat_maps",
    "google-services": "cat_google_services",
    "community": "cat_community",
    "media": "cat_media",
    "reference": "cat_reference",
}


def get_category_label(category_id: str, lang=None) -> str:
    try:
        from .i18n import tr
    except Exception:
        return dict(CATEGORIES).get(category_id, category_id)
    key = _CATEGORY_TR_KEYS.get(category_id)
    if key is None:
        return dict(CATEGORIES).get(category_id, category_id)
    label = tr(key, lang=lang)
    return label if label != key else dict(CATEGORIES).get(category_id, category_id)