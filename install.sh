#!/usr/bin/env bash
#
# install.sh
# Installs the Virtual monitor for the current user: app, icon and menu launcher.
# Run without sudo. Only the EDID install (inside the app) asks for a password.
#
# Usage:
#   bash install.sh [--dev] [--dest-dir DIR] [--skip-check] [--uninstall] [--help]

set -euo pipefail

NAME="virtual-monitor"
DIR="$(cd "$(dirname "$0")" && pwd)"

# Names used by the old Portuguese-named version, cleaned up on user installs
LEGACY_NAME="monitor-virtual"
LEGACY_AUTOSTART_NAME="monitor-virtual-restaurar"
LEGACY_MODE_FILE="modo.json"

HELP="Virtual monitor installer

Usage: bash install.sh [options]

  --dev             Link to this folder (development).
  --dest-dir DIR    Install into another data folder, without updating caches or the autostart.
  --skip-check      Do not check the app dependencies.
  --uninstall       Remove the app, icon, launcher and the resolution autostart.
  --help, -h        Show this help.

With no options, installs a copy in ~/.local/share/${NAME}.
Run without sudo."

DEV=0
SKIP_CHECK=0
UNINSTALL=0
DEST=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) echo "$HELP"; exit 0 ;;
        --dev) DEV=1 ;;
        --skip-check) SKIP_CHECK=1 ;;
        --uninstall) UNINSTALL=1 ;;
        --dest-dir)
            [[ $# -ge 2 && "$2" != -* ]] || { echo "--dest-dir needs a path." >&2; exit 1; }
            DEST="$2"
            shift
            ;;
        *) echo "Unknown option: $1. Use --help." >&2; exit 1 ;;
    esac
    shift
done

[[ "$(id -u)" -ne 0 ]] || { echo "Run without sudo to install for your user." >&2; exit 1; }

# Absolute XDG path, or the default
xdg() {
    local value="$1" default="$2"
    if [[ "$value" != /* ]]; then
        echo "$default"
        return
    fi

    echo "$value"
}

# The data folder: --dest-dir (created, made absolute) or the user's XDG one
data_dir() {
    if [[ -n "$DEST" ]]; then
        mkdir -p "$DEST"
        (cd "$DEST" && pwd)
        return
    fi

    xdg "${XDG_DATA_HOME:-}" "$HOME/.local/share"
}

DATA="$(data_dir)"
CONFIG="$(xdg "${XDG_CONFIG_HOME:-}" "$HOME/.config")"

APP="$DATA/$NAME"
ICON="$DATA/icons/hicolor/512x512/apps/$NAME.png"
LAUNCHER="$DATA/applications/$NAME.desktop"
AUTOSTART="$CONFIG/autostart/$NAME-restore.desktop"

LEGACY_APP="$DATA/$LEGACY_NAME"
LEGACY_ICON="$DATA/icons/hicolor/512x512/apps/$LEGACY_NAME.png"
LEGACY_LAUNCHER="$DATA/applications/$LEGACY_NAME.desktop"
LEGACY_AUTOSTART="$CONFIG/autostart/$LEGACY_AUTOSTART_NAME.desktop"
LEGACY_MODE="$CONFIG/$LEGACY_NAME/$LEGACY_MODE_FILE"
MODE="$CONFIG/$NAME/mode.json"

# With --dest-dir the install is standalone: it leaves the user's caches and autostart alone
is_user_install() {
    [[ -z "$DEST" ]]
}

update_caches() {
    is_user_install || return 0
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t "$DATA/icons/hicolor" 2>/dev/null || true
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$DATA/applications" 2>/dev/null || true
    fi
}

# Removes the files of the old Portuguese-named install (user installs only)
remove_legacy() {
    is_user_install || return 0
    rm -rf "$LEGACY_APP"
    rm -f "$LEGACY_ICON" "$LEGACY_LAUNCHER" "$LEGACY_AUTOSTART"
}

remove_autostart() {
    is_user_install || return 0
    rm -f "$AUTOSTART"
}

uninstall() {
    rm -rf "$APP"
    rm -f "$ICON" "$LAUNCHER"
    remove_autostart
    remove_legacy
    update_caches

    echo "Removed: $APP, $ICON, $LAUNCHER"
    echo "The remembered resolution stays in $CONFIG/$NAME; delete it if you no longer want it."
    exit 0
}

check_dependencies() {
    [[ $SKIP_CHECK -eq 0 ]] || return 0
    command -v python3 >/dev/null 2>&1 || { echo "Missing python3." >&2; exit 1; }

    if ! python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")' 2>/dev/null; then
        echo "GTK 4 or libadwaita for Python is missing. On Debian/Ubuntu/Armbian:" >&2
        echo "  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1" >&2
        exit 1
    fi

    command -v pkexec >/dev/null 2>&1 || echo "Warning: without pkexec the EDID Install button does not work (package policykit-1 or polkit)."
}

# Copies one app file into the staging folder; --dev links it to this checkout instead
stage_file() {
    local file="$1"
    mkdir -p "$(dirname "$STAGING/app/$file")"
    if [[ $DEV -eq 1 ]]; then
        ln -s "$DIR/$file" "$STAGING/app/$file"
        return
    fi

    install -m 644 "$DIR/$file" "$STAGING/app/$file"
}

# Migrates the old Portuguese-named install: remembered resolution and autostart
migrate_legacy() {
    is_user_install || return 0
    if [[ -f "$LEGACY_MODE" && ! -f "$MODE" ]]; then
        mkdir -p "$(dirname "$MODE")"
        cp "$LEGACY_MODE" "$MODE"
        echo "Migrated: $LEGACY_MODE -> $MODE"
    fi

    [[ -f "$LEGACY_AUTOSTART" ]] || return 0
    mkdir -p "$(dirname "$AUTOSTART")"
    cat > "$AUTOSTART" <<EOF
[Desktop Entry]
Type=Application
Name=Virtual monitor (restore resolution)
Exec=python3 "$APP/$NAME.py" --restore
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF
    echo "Autostart migrated: $AUTOSTART"
}

if [[ $UNINSTALL -eq 1 ]]; then
    uninstall
fi

FILES=("$NAME.py" scripts/install-edid.sh)
for module in "$DIR"/virtual_monitor/*.py; do
    FILES+=("virtual_monitor/$(basename "$module")")
done

for file in "${FILES[@]}" "assets/$NAME.png" "data/$NAME.desktop"; do
    [[ -f "$DIR/$file" ]] || { echo "Missing file: $file" >&2; exit 1; }
done

# The destination cannot be inside this folder nor contain it
case "$APP/" in "$DIR"/*) echo "Destination cannot be inside the project folder." >&2; exit 1 ;; esac
case "$DIR/" in "$APP"/*) echo "Destination cannot contain the project folder." >&2; exit 1 ;; esac

check_dependencies

mkdir -p "$DATA"
STAGING="$(mktemp -d "$DATA/.${NAME}-install-XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT

for file in "${FILES[@]}"; do
    stage_file "$file"
done
[[ $DEV -eq 1 ]] || chmod 755 "$STAGING/app/$NAME.py" "$STAGING/app/scripts/install-edid.sh"

install -m 644 "$DIR/assets/$NAME.png" "$STAGING/icon.png"

sed -E "s#^Exec=.*#Exec=python3 \"$APP/$NAME.py\"#; s#^Icon=.*#Icon=$ICON#" \
    "$DIR/data/$NAME.desktop" > "$STAGING/launcher.desktop"
chmod 644 "$STAGING/launcher.desktop"

mkdir -p "$(dirname "$ICON")" "$(dirname "$LAUNCHER")"
rm -rf "$APP"
mv "$STAGING/app" "$APP"
mv -f "$STAGING/icon.png" "$ICON"
mv -f "$STAGING/launcher.desktop" "$LAUNCHER"

migrate_legacy
remove_legacy

update_caches

echo "App installed: $APP"
echo "Icon installed: $ICON"
echo "Launcher installed: $LAUNCHER"
echo "Open it from the menu (Virtual monitor) or with: python3 \"$APP/$NAME.py\""
