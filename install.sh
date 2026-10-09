#!/bin/sh
#
# Remote installer for GNOME Web Search Provider. Downloads the source archive
# from GitHub and installs it for the current user, without cloning the repo:
#
#   curl -fsSL https://raw.githubusercontent.com/zonaro/gnome-web-search-provider/master/install.sh | sh
#
# Override REPO (owner/name) or REF (branch/tag) with environment variables.
set -eu

REPO="${REPO:-zonaro/gnome-web-search-provider}"
REF="${REF:-master}"

say() { printf '%s\n' "$*"; }
die() { printf 'Erro: %s\n' "$*" >&2; exit 1; }

command -v tar >/dev/null 2>&1 || die "tar nao encontrado."
command -v python3 >/dev/null 2>&1 || die "python3 nao encontrado (instale o Python 3.8+)."

if command -v curl >/dev/null 2>&1; then
    download() { curl -fsSL "$1"; }
elif command -v wget >/dev/null 2>&1; then
    download() { wget -qO- "$1"; }
else
    die "instale curl ou wget."
fi

TARBALL="https://github.com/${REPO}/archive/refs/heads/${REF}.tar.gz"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT INT TERM

say "==> Baixando ${REPO} (${REF})"
mkdir -p "$TMP/src"
download "$TARBALL" | tar -xz -C "$TMP/src" --strip-components=1
[ -f "$TMP/src/install-local.sh" ] || die "pacote invalido: install-local.sh ausente."

say "==> Instalando (sem clonar o repositorio)"
cd "$TMP/src"
sh install-local.sh

say "==> Pronto! Deslogue e relogue para ativar."
