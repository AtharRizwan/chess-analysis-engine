#!/usr/bin/env bash
# Download the official Stockfish release binary into ./bin/stockfish.
# Alternative on Arch Linux: `yay -S stockfish` (AUR) — the app also finds `stockfish` on PATH.
set -euo pipefail

VERSION="${STOCKFISH_VERSION:-sf_19}"
ASSET="stockfish-linux-x86-64-universal"
URL="https://github.com/official-stockfish/Stockfish/releases/download/${VERSION}/${ASSET}.tar.gz"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ROOT}/bin"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

echo "Downloading ${URL}"
curl -fL --progress-bar -o "${TMP}/stockfish.tar.gz" "${URL}"
tar -xzf "${TMP}/stockfish.tar.gz" -C "${TMP}"

BINARY="$(find "${TMP}" -type f -name "${ASSET}" -perm -u+x | head -n 1)"
if [[ -z "${BINARY}" ]]; then
  echo "Could not find ${ASSET} inside the archive" >&2
  exit 1
fi

mkdir -p "${DEST}"
install -m 0755 "${BINARY}" "${DEST}/stockfish"
echo "Installed $(echo quit | "${DEST}/stockfish" | head -n 1) -> ${DEST}/stockfish"
