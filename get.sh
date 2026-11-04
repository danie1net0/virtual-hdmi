#!/usr/bin/env bash
#
# get.sh
# Downloads the Virtual monitor and installs it for the current user with install.sh.
# Needs only curl and tar; run it again to update.
#
# Usage:
#   curl -fsSL https://gitlab.com/danie1net0/virtual-hdmi/-/raw/master/get.sh | bash
#   curl -fsSL https://gitlab.com/danie1net0/virtual-hdmi/-/raw/master/get.sh | bash -s -- --uninstall
#   curl -fsSL https://gitlab.com/danie1net0/virtual-hdmi/-/raw/master/get.sh | VERSION=v0.2.0 bash
# Options after "--" go to install.sh (see bash install.sh --help). VERSION is a tag or branch
# (default: master).
#
# Run without sudo. The EDID changes the boot, so it stays apart: the Install button in the app
# or sudo bash scripts/install-edid.sh.

set -euo pipefail

REPOSITORY="https://gitlab.com/danie1net0/virtual-hdmi"
WORK=""

fail() {
    echo "$1" >&2
    exit 1
}

check_arguments() {
    local version="$1" arg
    shift
    [[ "$version" =~ ^[A-Za-z0-9._-]+$ ]] || fail "Invalid VERSION: $version"

    for arg in "$@"; do
        [[ "$arg" != --dev ]] || fail "--dev links to a checkout; clone the repository and run bash install.sh --dev."
    done
}

# Everything runs from here, on the last line: a download cut in the middle executes nothing
main() {
    local version="${VERSION:-master}" archive
    command -v curl >/dev/null 2>&1 || fail "Missing curl."
    command -v tar >/dev/null 2>&1 || fail "Missing tar."
    check_arguments "$version" "$@"

    WORK="$(mktemp -d)"
    trap 'rm -rf "$WORK"' EXIT

    archive="$REPOSITORY/-/archive/$version/virtual-hdmi-$version.tar.gz"
    echo "==> Downloading $archive"
    curl -fsSL "$archive" | tar -xz -C "$WORK" --strip-components=1

    echo "==> Installing"
    bash "$WORK/install.sh" "$@" < /dev/null
}

main "$@"
