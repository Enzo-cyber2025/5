#!/data/data/com.termux/files/usr/bin/bash
# Reviewed, minimal install of the pinned third-party Termux ARM64 Box64 release.
# Source: https://github.com/wirawira941/box64-termux/releases/tag/v0.4.5-termux.1
# Its README and installer were inspected; release payload SHA-256 is pinned here.
set -euo pipefail

TAG="v0.4.5-termux.1"
VERSION="0.4.5"
ASSET="box64_${VERSION}_termux_arm64.tar.gz"
SHA256="0dae8257ac7396db4766721e5e4f317679b2080752d32e90d4e6e6fdfee467cf"
URL="https://github.com/wirawira941/box64-termux/releases/download/${TAG}/${ASSET}"

if [ "$(uname -m)" != "aarch64" ]; then
    echo "This pinned Box64 build requires Termux on Android arm64 (aarch64)." >&2
    exit 2
fi
if [ -z "${PREFIX:-}" ] || [ -z "${HOME:-}" ]; then
    echo "Run this script inside the Termux app." >&2
    exit 2
fi

pkg install -y curl libandroid-sysv-semaphore util-linux
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
curl --fail --location --retry 3 --max-time 300 --output "$WORK/$ASSET" "$URL"
echo "${SHA256}  ${WORK}/${ASSET}" | sha256sum --check -

# Extract only the two expected regular-file payloads to avoid honoring archive
# paths or links. The checksum is also verified before any payload is extracted.
mapfile -t MEMBERS < <(tar -tzf "$WORK/$ASSET")
BOX_MEMBER=""
for member in "${MEMBERS[@]}"; do
    case "${member##*/}" in
        box64) BOX_MEMBER="$member" ;;
        dragon) : ;;
        *) echo "Unexpected entry in pinned Box64 archive: $member" >&2; exit 3 ;;
    esac
done
[ -n "$BOX_MEMBER" ] || { echo "Box64 executable missing from archive" >&2; exit 3; }
tar -xOzf "$WORK/$ASSET" "$BOX_MEMBER" > "$WORK/box64"
install -m 0755 "$WORK/box64" "$PREFIX/bin/box64"
"$PREFIX/bin/box64" --version | head -1
