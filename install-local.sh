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

# 4) Desktop entries (Exec rewritten to ~/.local/bin)
sed "$RP" \
    data/org.gnome.WebSearch.SearchProvider.desktop \
    > "$DEST_SHARE/applications/org.gnome.WebSearch.SearchProvider.desktop"
sed -e "s|/usr/local/bin/gnome-web-search-provider-config|$DEST_BIN/gnome-web-search-provider-config|" \
    data/org.gnome.WebSearch.SearchProviderConfig.desktop \
    > "$DEST_SHARE/applications/org.gnome.WebSearch.SearchProviderConfig.desktop"
chmod +x "$DEST_SHARE/applications/org.gnome.WebSearch.SearchProvider.desktop" \
    "$DEST_SHARE/applications/org.gnome.WebSearch.SearchProviderConfig.desktop"
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DEST_SHARE/applications" 2>/dev/null || true
fi

# 5) D-Bus session service
sed "$RP" \
    data/org.gnome.WebSearch.SearchProvider.service \
    > "$DEST_SHARE/dbus-1/services/org.gnome.WebSearch.SearchProvider.service"
chmod +x "$DEST_SHARE/dbus-1/services/org.gnome.WebSearch.SearchProvider.service"

# 6) GNOME Shell search provider discovery
cp data/org.gnome.WebSearch.SearchProvider.ini \
    "$DEST_SHARE/gnome-shell/search-providers/"

echo "==> Concluído!"
echo "    Deslogue e relogue (ou reinicie o GNOME Shell) para ativar."
echo "    Depois:  gnome-web-search-provider-config  (tela de provedores)"
echo "    ou:      gnome-web-search-provider-cli list"
echo "    ou:      gsettings get org.gnome.WebSearch.SearchProvider enabled-providers"