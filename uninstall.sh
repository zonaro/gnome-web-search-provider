#!/bin/sh
#
# Uninstaller for GNOME Web Search Provider.
#
# Undoes everything install-local.sh installed for the current user, plus the
# system-wide search-provider manifest it copies with sudo and the data files a
# `sudo pip install .` places under /usr/local.
#
# From a clone:
#   sh uninstall.sh            # keep settings and custom providers
#   sh uninstall.sh --purge    # also delete settings, custom providers, cache
#
# Remotely, without cloning:
#   curl -fsSL https://raw.githubusercontent.com/zonaro/gnome-web-search-provider/master/uninstall.sh | sh
#   curl -fsSL https://raw.githubusercontent.com/zonaro/gnome-web-search-provider/master/uninstall.sh | sh -s -- --purge
set -eu

PURGE=0
for arg in "$@"; do
    case "$arg" in
        --purge|-p) PURGE=1 ;;
        -h|--help)
            cat <<'USAGE'
Remover o GNOME Web Search Provider para o usuario atual.

Uso:
  sh uninstall.sh [--purge]

Opcoes:
  -p, --purge   Tambem apaga suas configuracoes, provedores personalizados e o
                cache de favicons (~/.config/gnome-web-search-provider e
                ~/.cache/gnome-web-search-provider).
  -h, --help    Mostra esta ajuda.

Remoto (sem clonar):
  curl -fsSL https://raw.githubusercontent.com/zonaro/gnome-web-search-provider/master/uninstall.sh | sh
  curl -fsSL https://raw.githubusercontent.com/zonaro/gnome-web-search-provider/master/uninstall.sh | sh -s -- --purge
USAGE
            exit 0
            ;;
        *)
            printf 'Erro: opcao desconhecida: %s\n' "$arg" >&2
            printf 'Use --help para ver as opcoes.\n' >&2
            exit 1
            ;;
    esac
done

say() { printf '%s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

CONFIG_BASE="${XDG_CONFIG_HOME:-$HOME/.config}"
CACHE_BASE="${XDG_CACHE_HOME:-$HOME/.cache}"

# Remove a user-owned path. $2 = "recursive" selects rm -rf (for directories).
remove_path() {
    if [ -e "$1" ]; then
        if [ "${2:-}" = "recursive" ]; then
            rm -rf "$1"
        else
            rm -f "$1"
        fi
        say "    removido: $1"
    else
        say "    nao encontrado: $1"
    fi
}

# Remove a root-owned path under /usr/local, falling back to a printed command
# when sudo is unavailable. Never aborts the script.
remove_system_path() {
    if [ -e "$1" ]; then
        if have sudo; then
            if sudo rm -f "$1"; then
                say "    removido: $1"
            else
                say "    AVISO: falha ao remover: $1"
            fi
        else
            say "    AVISO: sem sudo; remova manualmente:"
            say "      sudo rm -f \"$1\""
        fi
    else
        say "    nao encontrado: $1"
    fi
}

PYTHON="${PYTHON:-python3}"
DEST_LIB=""
if have "$PYTHON"; then
    DEST_LIB="$("$PYTHON" -c 'import site; print(site.getusersitepackages())' 2>/dev/null || true)"
fi

say "==> Removendo o GNOME Web Search Provider (usuario)"

# 1) Launchers -> ~/.local/bin
remove_path "$HOME/.local/bin/gnome-web-search-provider"
remove_path "$HOME/.local/bin/gnome-web-search-provider-config"
remove_path "$HOME/.local/bin/gnome-web-search-provider-cli"

# 2) Python package -> user site-packages
if [ -n "$DEST_LIB" ]; then
    remove_path "$DEST_LIB/gnome_web_search_provider" recursive
else
    say "    AVISO: nao foi possivel localizar o user site-packages; pule a remocao"
    say "           do pacote Python (remova a mao a pasta gnome_web_search_provider)."
fi

# 3) GSettings schema + recompile so GLib forgets it
remove_path "$HOME/.local/share/glib-2.0/schemas/org.gnome.WebSearch.SearchProvider.gschema.xml"
if have glib-compile-schemas && [ -d "$HOME/.local/share/glib-2.0/schemas" ]; then
    glib-compile-schemas "$HOME/.local/share/glib-2.0/schemas" 2>/dev/null || true
fi

# 4) Desktop entries (config app + legacy ghost)
remove_path "$HOME/.local/share/applications/org.gnome.WebSearch.SearchProviderConfig.desktop"
remove_path "$HOME/.local/share/applications/org.gnome.WebSearch.SearchProvider.desktop"
if have update-desktop-database && [ -d "$HOME/.local/share/applications" ]; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

# 5) D-Bus activation service
remove_path "$HOME/.local/share/dbus-1/services/org.gnome.WebSearch.SearchProvider.service"

# 6) Shell search-provider manifest (user copy)
remove_path "$HOME/.local/share/gnome-shell/search-providers/org.gnome.WebSearch.SearchProvider.ini"

# 7) Forget stored settings (safe no-op when the schema is already gone)
if have gsettings; then
    gsettings reset-recursively org.gnome.WebSearch.SearchProvider 2>/dev/null || true
fi

say ""
say "==> Removendo os arquivos do sistema (/usr/local; requer sudo)"
remove_system_path /usr/local/share/gnome-shell/search-providers/org.gnome.WebSearch.SearchProvider.ini
remove_system_path /usr/local/share/applications/org.gnome.WebSearch.SearchProviderConfig.desktop
remove_system_path /usr/local/share/applications/org.gnome.WebSearch.SearchProvider.desktop
remove_system_path /usr/local/share/glib-2.0/schemas/org.gnome.WebSearch.SearchProvider.gschema.xml
remove_system_path /usr/local/share/dbus-1/services/org.gnome.WebSearch.SearchProvider.service

if have sudo; then
    if have glib-compile-schemas && [ -d /usr/local/share/glib-2.0/schemas ]; then
        sudo glib-compile-schemas /usr/local/share/glib-2.0/schemas 2>/dev/null || true
    fi
    if have update-desktop-database && [ -d /usr/local/share/applications ]; then
        sudo update-desktop-database /usr/local/share/applications 2>/dev/null || true
    fi
else
    say "    AVISO: sem sudo; recompile os schemas manualmente:"
    say "      sudo glib-compile-schemas /usr/local/share/glib-2.0/schemas/"
fi

say ""
if [ "$PURGE" = "1" ]; then
    say "==> Removendo dados do usuario (--purge)"
    remove_path "$CONFIG_BASE/gnome-web-search-provider" recursive
    remove_path "$CACHE_BASE/gnome-web-search-provider" recursive
else
    say "==> Dados do usuario mantidos:"
    say "      $CONFIG_BASE/gnome-web-search-provider"
    say "      $CACHE_BASE/gnome-web-search-provider"
    say "    Rode com --purge para apaga-los tambem."
fi

say ""
say "==> Concluído!"
say "    Deslogue e relogue (ou reinicie o GNOME Shell) para o provedor sumir de vez."
say "    Se ele foi instalado no sistema com 'sudo pip install .', remova o pacote com:"
say "      sudo pip uninstall gnome-web-search-provider"
