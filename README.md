# 🌐 GNOME Web Search Provider

A GNOME Shell search provider that lets you search the web directly from the
Activities Overview (the `Super` key search box), choosing **one or more
search engines at the same time** — Google, Bing, DuckDuckGo, Brave, Startpage
and many more.

Every enabled provider shows its own result entry in the overview
("Search Google for 'linux'", "Search Bing for 'linux'", ...). Press Enter to
open the chosen engine in your default browser.

![image](https://github.com/user-attachments/assets/9a26a63e-412f-4925-8a42-890878af3e00)

## Features

- 47 search providers, grouped by category (web, images, maps, videos,
  news, communities, media, reference/docs).
- Enable **any number of providers simultaneously** — they all appear as
  separate entries in the search overview.
- **Google is the only provider enabled by default.**
- Preferences window (`gnome-web-search-provider-config`) with a checkbox per
  provider; changes apply immediately, no reload needed.
- Native GNOME configuration via a **GSettings schema**
  (`org.gnome.WebSearch.SearchProvider`), so it can also be scripted with
  `gsettings`, with a transparent JSON fallback
  (`~/.config/gnome-web-search-provider/config.json`) when the schema is not
  installed.
- Search URLs verified in 2026 (including Google's new `udm=` verticals and
  Marginalia's new domain).

## Available providers

| Category | Providers |
|---|---|
| **Web Search** | Google (default), Bing, DuckDuckGo, Brave Search, Startpage, Ecosia, Qwant, Yahoo, Mojeek, Yandex, Baidu, Naver, SearXNG, Yep (Ahrefs), Swisscows, Marginalia, Perplexity |
| **Images** | Google Images, Bing Images, DuckDuckGo Images, Brave Images, Startpage Images |
| **Maps** | Google Maps, Bing Maps, OpenStreetMap |
| **Google Services** | Google News, Google Scholar, Google Videos, Google Translate (→ pt), Google Flights, Google Fonts |
| **Communities** | Reddit, Hacker News, GitHub, Stack Overflow |
| **Media** | YouTube, Spotify, IMDb, Steam |
| **Reference & Tech** | Wikipedia, Wiktionary, WolframAlpha, PyPI, MDN Web Docs, Docker Hub, Internet Archive, Arch Wiki |

> Kagi and You.com are intentionally **not** included: anonymous searches
> redirect to a sign-in page, which is a poor launcher experience.

## Requirements

- GNOME Shell (search providers need GNOME; the preferences app needs GTK4)
- Python 3.8+
- `dasbus`, `PyGObject` (with GTK4 bindings), `glib-compile-schemas`

**Fedora:**
```bash
sudo dnf install python3-dasbus python3-gobject gtk4 gobject-introspection-devel glib2-devel
```

**Ubuntu/Debian:**
```bash
sudo apt install python3-dasbus python3-gi gir1.2-gtk-4.0 libgirepository1.0-dev glib-compile-schemas
```

## Installation

Install the Python package system-wide (the desktop/service files expect the
binaries in `/usr/local/bin`):

```bash
sudo pip install .
```

Register the GSettings schema so the provider and the preferences window can
use it (and pick up the desktop file):

```bash
sudo glib-compile-schemas /usr/local/share/glib-2.0/schemas/
sudo update-desktop-database /usr/local/share/applications/
```

### Activate the provider

1. Log out and back in (or restart GNOME Shell) so the D-Bus service file and
   the search provider are discovered automatically.
2. GNOME Shell discovers the provider via
   `/usr/local/share/gnome-shell/search-providers/org.gnome.WebSearch.SearchProvider.ini`
   and autostarts it on demand. Toggle it in **Settings > Search** if needed.

## Configuration

### Preferences window (recommended)

Launch **Web Search Providers** from the app grid, or run:

```bash
gnome-web-search-provider-config
```

Tick the providers you want — each one becomes an entry in the overview
search. "All"/"None" enable or disable everything at once. Changes are
written immediately.

### CLI (GSettings)

When installed with the schema, the same setting is available via
`gsettings`:

```bash
# Show current providers
gsettings get org.gnome.WebSearch.SearchProvider enabled-providers

# Enable Google + DuckDuckGo
gsettings set org.gnome.WebSearch.SearchProvider enabled-providers "['google', 'duckduckgo']"

# Restore the default (only Google)
gsettings reset org.gnome.WebSearch.SearchProvider enabled-providers
```

Valid provider ids are the keys listed in `src/gnome_web_search_provider/providers.py`
(e.g. `google`, `bing`, `duckduckgo`, `brave`, `startpage`, `google-images`,
`google-maps`, `bing-images`, `youtube`, ...). Unknown ids are ignored.

### JSON fallback

Without the schema, settings live in
`~/.config/gnome-web-search-provider/config.json`:

```json
{ "enabled_providers": ["google", "bing"] }
```

Missing/corrupt files fall back to `["google"]`. Set `"enabled_providers": []`
to disable all providers.

## Development

```bash
git clone https://github.com/zonaro/gnome-web-search-provider.git
cd gnome-web-search-provider

# Run the test suite (no system install needed)
python3 -m unittest discover -s tests -v

# Run the provider in-place (no D-Bus registration issues in a terminal)
python3 -m gnome_web_search_provider   # needs src/ on PYTHONPATH

# Open the preferences window against the JSON fallback
PYTHONPATH=src python3 -m gnome_web_search_provider.config_app
```

Layout:

```
data/    GSettings schema, desktop entries, D-Bus service, shell .ini
src/     gnome_web_search_provider/ package (provider, providers registry,
         config manager, GTK4 preferences app)
tests/   unit tests
```

## Goals

* **P0** — Search the web from the GNOME Shell overview
* **P0** — Package as a real extension (pip + system data files)
* **P1** — Configuration UI to pick one or more search engines ✅
* **P1** — Integrate suggestions for partial search terms

## Non-Goals

* Update the Activities Overview search results UI elements

## License

MIT, see [LICENSE](LICENSE). Forked from
[quiquevr/gnome-web-search-provider](https://github.com/quiquevr/gnome-web-search-provider).