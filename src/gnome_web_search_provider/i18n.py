"""Trilingual UI strings (pt_BR / es / en), auto-detect with en fallback.

Order: override > GWSP_LANG > LANGUAGE > LC_ALL > LANG > locale.
``pt*`` -> pt_BR, ``es*`` -> es, else ``en``. Stdlib only, never raises.
"""

import locale
import os
from typing import Dict, Optional

SUPPORTED_LANGUAGES = ("en", "pt_BR", "es")
DEFAULT_LANGUAGE = "en"


def _normalize(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    code = raw.strip().replace("-", "_")
    # LANGUAGE may be "pt_BR:pt:en"; LC vars may carry ".UTF-8"/"@mod".
    code = code.split(":")[0].split()[0].split(".")[0].split("@")[0]
    return code.lower() or None


def _map(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    if code in ("c", "posix"):
        return "en"
    if code.startswith("pt"):
        return "pt_BR"
    if code.startswith("es"):
        return "es"
    if code.startswith("en"):
        return "en"
    return None


def get_language(lang_override: Optional[str] = None) -> str:
    """Return ``pt_BR`` | ``es`` | ``en`` for this machine (fallback ``en``)."""
    if lang_override is not None:
        mapped = _map(_normalize(lang_override))
        return mapped if mapped else DEFAULT_LANGUAGE
    for var in ("GWSP_LANG", "LANGUAGE", "LC_ALL", "LANG"):
        raw = os.environ.get(var)
        if raw and raw.strip():
            mapped = _map(_normalize(raw))
            return mapped if mapped else DEFAULT_LANGUAGE
    try:
        mapped = _map(_normalize((locale.getdefaultlocale()[0] or "")))
        if mapped:
            return mapped
    except Exception:
        pass
    try:
        loc = locale.getlocale()[0] or ""
        mapped = _map(_normalize(loc))
        if mapped:
            return mapped
    except Exception:
        pass
    return DEFAULT_LANGUAGE


STRINGS: Dict[str, Dict[str, str]] = {
    "search_for": {
        "en": "Search {provider} for '{query}'",
        "pt_BR": "Pesquisar {provider} por '{query}'",
        "es": "Buscar {provider} para '{query}'",
    },
    "press_enter": {
        "en": "Press Enter to open in browser",
        "pt_BR": "Pressione Enter para abrir no navegador",
        "es": "Pulse Enter para abrir en el navegador",
    },
    "service_running": {
        "en": "Service running at {bus}...",
        "pt_BR": "Serviço em execução em {bus}...",
        "es": "Servicio en ejecución en {bus}...",
    },
    "service_error": {
        "en": "Error starting service: {error}",
        "pt_BR": "Erro ao iniciar o serviço: {error}",
        "es": "Error al iniciar el servicio: {error}",
    },
    "window_title": {
        "en": "Web Search Providers",
        "pt_BR": "Provedores de Busca Web",
        "es": "Proveedores de búsqueda web",
    },
    "btn_all": {"en": "All", "pt_BR": "Todos", "es": "Todos"},
    "btn_all_tooltip": {
        "en": "Enable every search provider",
        "pt_BR": "Habilitar todos os provedores de busca",
        "es": "Habilitar todos los proveedores de búsqueda",
    },
    "btn_none": {"en": "None", "pt_BR": "Nenhum", "es": "Ninguno"},
    "btn_none_tooltip": {
        "en": "Disable every search provider",
        "pt_BR": "Desabilitar todos os provedores de busca",
        "es": "Deshabilitar todos los proveedores de búsqueda",
    },
    "btn_search_settings": {
        "en": "GNOME Search Settings",
        "pt_BR": "Configurações de Busca do GNOME",
        "es": "Ajustes de búsqueda de GNOME",
    },
    "search_placeholder": {
        "en": "Search providers…",
        "pt_BR": "Buscar provedores…",
        "es": "Buscar proveedores…",
    },
    "refresh_tooltip": {
        "en": "Download the real site icons (favicons) for each provider",
        "pt_BR": "Baixar os ícones reais dos sites (favicons) de cada provedor",
        "es": "Descargar los iconos reales de los sitios (favicons) de cada proveedor",
    },
    "browser_label": {
        "en": "Browser command",
        "pt_BR": "Comando do navegador",
        "es": "Comando del navegador",
    },
    "browser_placeholder": {"en": "xdg-open", "pt_BR": "xdg-open", "es": "xdg-open"},
    "browser_tooltip": {
        "en": "Command used to open search results, e.g. xdg-open (default), firefox, google-chrome, or 'flatpak run org.mozilla.firefox'. Press Enter to apply.",
        "pt_BR": "Comando usado para abrir os resultados, ex.: xdg-open (padrão), firefox, google-chrome ou 'flatpak run org.mozilla.firefox'. Pressione Enter para aplicar.",
        "es": "Comando para abrir los resultados, p. ej. xdg-open (predeterminado), firefox, google-chrome o 'flatpak run org.mozilla.firefox'. Pulse Enter para aplicar.",
    },
    "footer_text": {
        "en": "Each enabled provider adds an entry to the GNOME Shell search results in the Activities overview.\nChanges are saved and applied immediately.",
        "pt_BR": "Cada provedor habilitado adiciona uma entrada aos resultados de busca do GNOME Shell na visão de Atividades.\nAs alterações são salvas e aplicadas imediatamente.",
        "es": "Cada proveedor habilitado añade una entrada a los resultados de búsqueda de GNOME Shell en la vista de Actividades.\nLos cambios se guardan y aplican de inmediato.",
    },
    "toggle_tooltip": {
        "en": "Toggle {name}",
        "pt_BR": "Alternar {name}",
        "es": "Alternar {name}",
    },
    "switch_tooltip": {
        "en": "Enable/disable {name}",
        "pt_BR": "Habilitar/desabilitar {name}",
        "es": "Habilitar/deshabilitar {name}",
    },
    "no_gtk_message": {
        "en": "The GNOME web search provider config window needs PyGObject and GTK4. Install python3-gobject / python3-gi with GTK4, or configure providers from the terminal instead: gnome-web-search-provider-cli",
        "pt_BR": "A janela de configuração precisa de PyGObject e GTK4. Instale python3-gobject / python3-gi com GTK4, ou configure os provedores pelo terminal: gnome-web-search-provider-cli",
        "es": "La ventana de configuración necesita PyGObject y GTK4. Instale python3-gobject / python3-gi con GTK4, o configure los proveedores desde la terminal: gnome-web-search-provider-cli",
    },
    "cat_web": {"en": "Web Search", "pt_BR": "Busca Web", "es": "Búsqueda web"},
    "cat_images": {"en": "Images", "pt_BR": "Imagens", "es": "Imágenes"},
    "cat_maps": {"en": "Maps", "pt_BR": "Mapas", "es": "Mapas"},
    "cat_google_services": {
        "en": "Google Services",
        "pt_BR": "Serviços do Google",
        "es": "Servicios de Google",
    },
    "cat_community": {
        "en": "Communities & Forums",
        "pt_BR": "Comunidades & Fóruns",
        "es": "Comunidades y foros",
    },
    "cat_media": {
        "en": "Media & Entertainment",
        "pt_BR": "Mídia & Entretenimento",
        "es": "Medios y entretenimiento",
    },
    "cat_reference": {
        "en": "Reference & Tech Docs",
        "pt_BR": "Referência & Docs Técnicas",
        "es": "Referencia y docs técnicos",
    },
    "cli_description": {
        "en": "Configure the GNOME web search provider (no GUI required).",
        "pt_BR": "Configure o provedor de busca web do GNOME (sem interface gráfica).",
        "es": "Configure el proveedor de búsqueda web de GNOME (sin interfaz gráfica).",
    },
    "cli_list_help": {
        "en": "show providers and their enabled status",
        "pt_BR": "mostrar provedores e seus status",
        "es": "mostrar proveedores y su estado",
    },
    "cli_status_help": {
        "en": "alias for 'list'",
        "pt_BR": "atalho para 'list'",
        "es": "alias de 'list'",
    },
    "cli_enable_help": {
        "en": "enable one or more providers",
        "pt_BR": "habilitar um ou mais provedores",
        "es": "habilitar uno o más proveedores",
    },
    "cli_disable_help": {
        "en": "disable one or more providers",
        "pt_BR": "desabilitar um ou mais provedores",
        "es": "deshabilitar uno o más proveedores",
    },
    "cli_set_help": {
        "en": "replace the enabled providers list",
        "pt_BR": "substituir a lista de provedores habilitados",
        "es": "reemplazar la lista de proveedores habilitados",
    },
    "cli_browser_help": {
        "en": "get or set the browser command",
        "pt_BR": "ver ou definir o comando do navegador",
        "es": "ver o definir el comando del navegador",
    },
    "cli_backend": {"en": "Backend", "pt_BR": "Backend", "es": "Backend"},
    "cli_browser_label": {"en": "Browser", "pt_BR": "Navegador", "es": "Navegador"},
    "cli_providers_label": {
        "en": "Providers",
        "pt_BR": "Provedores",
        "es": "Proveedores",
    },
    "cli_unknown_providers": {
        "en": "Unknown provider(s): {ids}",
        "pt_BR": "Provedor(es) desconhecido(s): {ids}",
        "es": "Proveedor(es) desconocido(s): {ids}",
    },
    "cli_run_list_hint": {
        "en": "Run 'gnome-web-search-provider-cli list' for valid ids.",
        "pt_BR": "Execute 'gnome-web-search-provider-cli list' para ver os ids válidos.",
        "es": "Ejecute 'gnome-web-search-provider-cli list' para ver los ids válidos.",
    },
    "cli_enabled": {"en": "Enabled: {ids}", "pt_BR": "Habilitados: {ids}", "es": "Habilitados: {ids}"},
    "cli_disabled": {
        "en": "Disabled: {ids}",
        "pt_BR": "Desabilitados: {ids}",
        "es": "Deshabilitados: {ids}",
    },
    "cli_set_to": {
        "en": "Enabled providers set to: {ids}",
        "pt_BR": "Provedores habilitados definidos como: {ids}",
        "es": "Proveedores habilitados establecidos como: {ids}",
    },
    "cli_set_to_none": {
        "en": "(none)",
        "pt_BR": "(nenhum)",
        "es": "(ninguno)",
    },
    "cli_browser_set_to": {
        "en": "Browser set to: {value}",
        "pt_BR": "Navegador definido como: {value}",
        "es": "Navegador establecido como: {value}",
    },
}


def tr(key: str, lang: Optional[str] = None, **kwargs: object) -> str:
    """Translate ``key`` to ``lang`` (auto-detect when None), fallback ``en``."""
    if lang is None:
        effective = get_language()
    elif lang in SUPPORTED_LANGUAGES:
        effective = lang
    else:
        effective = DEFAULT_LANGUAGE
    entry = STRINGS.get(key)
    if not entry:
        return key
    template = entry.get(effective) or entry.get(DEFAULT_LANGUAGE) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except Exception:
            return template
    return template
