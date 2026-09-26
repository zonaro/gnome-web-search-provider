#!/bin/sh
# Install the GNOME web search provider for the current user (no root needed).
#
# Installs into ~/.local (bins, Python package, GSettings schema, desktop
# entries, D-Bus service and the GNOME Shell search-provider .ini), which
# GNOME picks up natively:
#   - ~/.local/bin                    -> gnome-web-search-provider{, -cli, -config}
#   - user site-packages              -> gnome_web_search_provider package
#   - ~/.local/share/glib-2.0/schemas -> GSettings schema (compiled)
#   - ~/.local/share/applications     -> desktop entries
#   - ~/.local/share/dbus-1/services  -> D-Bus activation service
#   - ~/.local/share/gnome-shell/search-providers -> shell provider ini
#
# After install: log out and back in so GNOME Shell discovers the provider.
set -eu

PYTHON="${PYTHON:-python3}"
DEST_BIN="${HOME}/.local/bin"
DEST_SHARE="${HOME}/.local/share"
DEST_LIB="$("$PYTHON" -c 'import site; print(site.getusersitepackages())')"

if [ -z "$DEST_LIB" ]; then
    echo "Erro: user site-packages nao disponivel para $PYTHON" >&2
    exit 1
fi

RP="-e s|/usr/local/bin/gnome-web-search-provider|$DEST_BIN/gnome-web-search-provider|g"

echo "==> Instalando em ~/.local (python: $PYTHON)"
mkdir -p "$DEST_LIB" "$DEST_BIN" \
    "$DEST_SHARE/glib-2.0/schemas" \
    "$DEST_SHARE/applications" \
    "$DEST_SHARE/dbus-1/services" \
    "$DEST_SHARE/gnome-shell/search-providers"

# 1) Python package -> user site-packages
rm -rf "$DEST_LIB/gnome_web_search_provider"
cp -r src/gnome_web_search_provider "$DEST_LIB/"

# 2) Launcher wrappers -> ~/.local/bin
# 2b) Best-effort favicon prefetch so overview results show site icons
# immediately (the config window refreshes them on open anyway).
"$PYTHON" -m gnome_web_search_provider.favicons >/dev/null 2>&1 || true
cat > "$DEST_BIN/gnome-web-search-provider" <<EOF
#!/bin/sh
exec "$PYTHON" -m gnome_web_search_provider "\$@"
EOF
cat > "$DEST_BIN/gnome-web-search-provider-config" <<EOF
#!/bin/sh
exec "$PYTHON" -m gnome_web_search_provider.config_app "\$@"
EOF
cat > "$DEST_BIN/gnome-web-search-provider-cli" <<EOF
#!/bin/sh
exec "$PYTHON" -m gnome_web_search_provider.cli "\$@"
EOF
chmod +x "$DEST_BIN/gnome-web-search-provider" \
    "$DEST_BIN/gnome-web-search-provider-config" \
    "$DEST_BIN/gnome-web-search-provider-cli"

# 3) GSettings schema (compiled -> detected by GLib)
cp data/org.gnome.WebSearch.SearchProvider.gschema.xml "$DEST_SHARE/glib-2.0/schemas/"
glib-compile-schemas "$DEST_SHARE/glib-2.0/schemas/"

# 4) Desktop entry (single visible app: the Config window. The Shell
#    search-provider .ini points its DesktopId at this file, because
#    gnome-shell ignores providers whose desktop should_show() is false
#    (i.e. NoDisplay=true). A separate hidden provider desktop would
#    never be loaded -- so there is intentionally only one .desktop.)
sed -e "s|/usr/local/bin/gnome-web-search-provider-config|$DEST_BIN/gnome-web-search-provider-config|" \
    data/org.gnome.WebSearch.SearchProviderConfig.desktop \
    > "$DEST_SHARE/applications/org.gnome.WebSearch.SearchProviderConfig.desktop"
chmod +x "$DEST_SHARE/applications/org.gnome.WebSearch.SearchProviderConfig.desktop"
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DEST_SHARE/applications" 2>/dev/null || true
fi

# 5) D-Bus session service
sed "$RP" \
    data/org.gnome.WebSearch.SearchProvider.service \
    > "$DEST_SHARE/dbus-1/services/org.gnome.WebSearch.SearchProvider.service"
chmod +x "$DEST_SHARE/dbus-1/services/org.gnome.WebSearch.SearchProvider.service"

# 6) GNOME Shell search provider discovery.
#    The .ini stays in ~/.local for reference, but GNOME Shell 40+ and
#    gnome-control-center only scan SYSTEM data dirs for search-providers
#    (collectFromDatadirs(..., includeUserDir=false)), so the .ini must
#    ALSO live in /usr/local/share (covered by XDG_DATA_DIRS). Needs sudo;
#    without it the provider won't appear until this is done manually.
cp data/org.gnome.WebSearch.SearchProvider.ini \
    "$DEST_SHARE/gnome-shell/search-providers/"
if command -v sudo >/dev/null 2>&1; then
    sudo mkdir -p /usr/local/share/gnome-shell/search-providers
    sudo cp data/org.gnome.WebSearch.SearchProvider.ini \
        /usr/local/share/gnome-shell/search-providers/
    sudo update-desktop-database /usr/local/share/applications 2>/dev/null || true
else
    echo "AVISO: sem sudo; copie manualmente:" >&2
    echo "  sudo cp data/org.gnome.WebSearch.SearchProvider.ini /usr/local/share/gnome-shell/search-providers/" >&2
fi

# 7) Remove the legacy ghost launcher (older versions installed a
#    separate visible/hidden "Web Search Provider" desktop that the Shell
#    either showed as a dead app or ignored). Only the Config desktop
#    remains; the .ini points at it.
rm -f "$DEST_SHARE/applications/org.gnome.WebSearch.SearchProvider.desktop" 2>/dev/null || true
if [ -f /usr/local/share/applications/org.gnome.WebSearch.SearchProvider.desktop ]; then
    if command -v sudo >/dev/null 2>&1; then
        sudo rm -f /usr/local/share/applications/org.gnome.WebSearch.SearchProvider.desktop 2>/dev/null || true
        sudo update-desktop-database /usr/local/share/applications 2>/dev/null || true
    else
        echo "AVISO: fantasma antigo em /usr/local/share/applications/org.gnome.WebSearch.SearchProvider.desktop" >&2
        echo "       remova manualmente para sumir o app 'Web Search Provider' que nao faz nada." >&2
    fi
fi

# 8) Favicons best-effort prefetch (real site icons into ~/.cache, used by
#    the config window with symbolic icons as fallback). Skipped when offline.
if "$PYTHON" -c "import socket; socket.create_connection(('8.8.8.8', 53), timeout=3)" 2>/dev/null; then
    PYTHONPATH="$DEST_LIB" "$PYTHON" -m gnome_web_search_provider.favicons 2>/dev/null || true
fi

echo "==> Concluído!"
echo "    Deslogue e relogue (ou reinicie o GNOME Shell) para ativar."
echo "    Depois:  gnome-web-search-provider-config  (tela de provedores)"
echo "    ou:      gnome-web-search-provider-cli list"
echo "    ou:      gsettings get org.gnome.WebSearch.SearchProvider enabled-providers"
echo ""
echo "    Verificacao (provider precisa aparecer em Configuracoes > Pesquisa):"
echo "      ls ~/.local/share/gnome-shell/search-providers/org.gnome.WebSearch.SearchProvider.ini"
echo "      gio launch ~/.local/share/applications/org.gnome.WebSearch.SearchProviderConfig.desktop 2>/dev/null || true"
echo "      gsettings get org.gnome.desktop.search-providers disabled  # nao deve conter o nosso BusName"
echo "    Se estiver disabled, reative com:"
echo "      gsettings reset org.gnome.desktop.search-providers disabled"