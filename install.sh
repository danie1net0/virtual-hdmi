#!/usr/bin/env bash
#
# install.sh
# Installs the Virtual monitor for the current user: app, icon, menu launcher and the
# virtual-monitor command in ~/.local/bin.
# Run without sudo. Only the EDID install and the automatic login ask for a password.
#
# Usage:
#   bash install.sh [--dev] [--dest-dir FOLDER] [--skip-check] [--uninstall] [--help]

set -euo pipefail

NAME="virtual-monitor"
PROJECT_FOLDER="$(cd "$(dirname "$0")" && pwd)"

# The launcher is named after the application id: Wayland docks find the icon of a window by its
# application id, which GTK takes from the application id (APPLICATION_ID in virtual_monitor/window.py).
APPLICATION_ID="br.app.VirtualMonitor"

# Names used by the old Portuguese-named version, cleaned up on user installs
LEGACY_NAME="monitor-virtual"
LEGACY_AUTOSTART_NAME="monitor-virtual-restaurar"
LEGACY_MODE_FILE="modo.json"

HELP="Virtual monitor installer

Usage: bash install.sh [options]

  --dev             Link to this folder (development).
  --dest-dir FOLDER Install into another data folder: no ~/.local/bin command, caches, autostart
                    or cleanup of the old install.
  --skip-check      Do not check the app dependencies.
  --uninstall       Remove the app, icon, launcher, command and the resolution autostart.
  --help, -h        Show this help.

With no options, installs a copy in ~/.local/share/${NAME} and the command ~/.local/bin/${NAME}.
Run without sudo."

DEVELOPMENT=0
SKIP_CHECK=0
UNINSTALL=0
DESTINATION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) echo "$HELP"; exit 0 ;;
        --dev) DEVELOPMENT=1 ;;
        --skip-check) SKIP_CHECK=1 ;;
        --uninstall) UNINSTALL=1 ;;
        --dest-dir)
            [[ $# -ge 2 && "$2" != -* ]] || { echo "--dest-dir needs a path." >&2; exit 1; }
            DESTINATION="$2"
            shift
            ;;
        *) echo "Unknown option: $1. Use --help." >&2; exit 1 ;;
    esac

    shift
done

[[ "$(id -u)" -ne 0 ]] || { echo "Run without sudo to install for your user." >&2; exit 1; }

# Absolute XDG path, or the default
xdg() (
    value="$1" default="$2"
    if [[ "$value" != /* ]]; then
        echo "$default"
        return
    fi

    echo "$value"
)

# The data folder: --dest-dir (created, made absolute) or the user's XDG one
data_folder() {
    if [[ -n "$DESTINATION" ]]; then
        mkdir -p "$DESTINATION"
        (cd "$DESTINATION" && pwd)
        return
    fi

    xdg "${XDG_DATA_HOME:-}" "$HOME/.local/share"
}

DATA="$(data_folder)"
CONFIGURATION_FOLDER="$(xdg "${XDG_CONFIG_HOME:-}" "$HOME/.config")"

APPLICATION_FOLDER="$DATA/$NAME"
ICON="$DATA/icons/hicolor/512x512/apps/$NAME.png"
LAUNCHER="$DATA/applications/$APPLICATION_ID.desktop"
# Name of the launcher up to v0.5.1, which Wayland docks did not match to the window
OLD_LAUNCHER="$DATA/applications/$NAME.desktop"
AUTOSTART="$CONFIGURATION_FOLDER/autostart/$NAME-restore.desktop"
COMMAND="$HOME/.local/bin/$NAME"

LEGACY_APPLICATION_FOLDER="$DATA/$LEGACY_NAME"
LEGACY_ICON="$DATA/icons/hicolor/512x512/apps/$LEGACY_NAME.png"
LEGACY_LAUNCHER="$DATA/applications/$LEGACY_NAME.desktop"
LEGACY_AUTOSTART="$CONFIGURATION_FOLDER/autostart/$LEGACY_AUTOSTART_NAME.desktop"
LEGACY_MODE="$CONFIGURATION_FOLDER/$LEGACY_NAME/$LEGACY_MODE_FILE"
MODE="$CONFIGURATION_FOLDER/$NAME/mode.json"

# With --dest-dir the install is standalone: no ~/.local/bin command, and it leaves the user's
# caches, autostart and old install alone
is_user_install() {
    [[ -z "$DESTINATION" ]]
}

update_caches() {
    is_user_install || return 0

    if command -v gtk-update-icon-cache >/dev/null; then
        gtk-update-icon-cache -q -t "$DATA/icons/hicolor" 2>/dev/null || echo "Warning: gtk-update-icon-cache failed; the icon may show only after logging in again."
    fi

    if command -v update-desktop-database >/dev/null; then
        update-desktop-database "$DATA/applications" 2>/dev/null || echo "Warning: update-desktop-database failed; the launcher may show only after logging in again."
    fi
}

# Removes the files of the old Portuguese-named install (user installs only)
remove_legacy() {
    is_user_install || return 0
    rm -rf "$LEGACY_APPLICATION_FOLDER"
    rm -f "$LEGACY_ICON" "$LEGACY_LAUNCHER" "$LEGACY_AUTOSTART"
}

remove_autostart() {
    is_user_install || return 0
    rm -f "$AUTOSTART"
}

remove_command() {
    is_user_install || return 0
    rm -f "$COMMAND"
}

# The virtual-monitor command: runs the app with its arguments, from any folder (user installs only)
install_command() {
    is_user_install || return 0
    mkdir -p "$(dirname "$COMMAND")"
    printf '#!/bin/sh\nexec python3 "%s/%s.py" "$@"\n' "$APPLICATION_FOLDER" "$NAME" > "$COMMAND"
    chmod 755 "$COMMAND"
    echo "Command installed: $COMMAND"
    warn_path
}

# ~/.local/bin enters PATH at the next login on most distributions, if it exists by then
warn_path() {
    case ":$PATH:" in *":$(dirname "$COMMAND"):"*) return 0 ;; esac
    echo "$(dirname "$COMMAND") is not in PATH yet: log in again, or run it as $COMMAND"
}

uninstall() {
    rm -rf "$APPLICATION_FOLDER"
    rm -f "$ICON" "$LAUNCHER" "$OLD_LAUNCHER"
    remove_command
    remove_autostart
    remove_legacy
    update_caches

    echo "Removed: $APPLICATION_FOLDER, $ICON, $LAUNCHER"
    is_user_install && echo "Removed: $COMMAND"
    echo "The remembered resolution stays in $CONFIGURATION_FOLDER/$NAME; delete it if you no longer want it."
    exit 0
}

check_dependencies() {
    [[ $SKIP_CHECK -eq 1 ]] && return 0
    command -v python3 >/dev/null || { echo "Missing python3." >&2; exit 1; }

    if ! python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")' 2>/dev/null; then
        echo "GTK 4 or libadwaita for Python is missing. On Debian/Ubuntu/Armbian:" >&2
        echo "  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1" >&2
        exit 1
    fi

    command -v pkexec >/dev/null || echo "Warning: without pkexec the EDID Install button does not work (package policykit-1 or polkit)."
}

# Copies one app file into the staging folder; --dev links it to this checkout instead
stage_file() (
    file="$1"
    mkdir -p "$(dirname "$STAGING/application/$file")"
    if [[ $DEVELOPMENT -eq 1 ]]; then
        ln -s "$PROJECT_FOLDER/$file" "$STAGING/application/$file"
        return
    fi

    install -m 644 "$PROJECT_FOLDER/$file" "$STAGING/application/$file"
)

# Migrates the old Portuguese-named install: remembered resolution and autostart
migrate_legacy() {
    is_user_install || return 0
    if [[ -f "$LEGACY_MODE" && ! -e "$MODE" ]]; then
        mkdir -p "$(dirname "$MODE")"
        cp "$LEGACY_MODE" "$MODE"
        echo "Migrated: $LEGACY_MODE -> $MODE"
    fi

    # The old autostart sits in the same folder as the new one
    [[ -e "$LEGACY_AUTOSTART" ]] || return 0
    cat > "$AUTOSTART" <<EOF
[Desktop Entry]
Type=Application
Name=Virtual monitor (restore resolution)
Exec=python3 "$APPLICATION_FOLDER/$NAME.py" --restore
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF
    echo "Autostart migrated: $AUTOSTART"
}

if [[ $UNINSTALL -eq 1 ]]; then
    uninstall
fi

FILES=("$NAME.py" scripts/install-edid.sh scripts/auto-login.sh)
for module in "$PROJECT_FOLDER"/virtual_monitor/*.py; do
    FILES+=("virtual_monitor/$(basename "$module")")
done

for project_file in "${FILES[@]}" "assets/$NAME.png" "data/$NAME.desktop"; do
    [[ -f "$PROJECT_FOLDER/$project_file" ]] || { echo "Missing file: $project_file" >&2; exit 1; }
done

# The destination cannot be inside this folder nor contain it
case "$APPLICATION_FOLDER/" in "$PROJECT_FOLDER"/*) echo "Destination cannot be inside the project folder." >&2; exit 1 ;; esac
case "$PROJECT_FOLDER/" in "$APPLICATION_FOLDER"/*) echo "Destination cannot contain the project folder." >&2; exit 1 ;; esac

check_dependencies

mkdir -p "$DATA"
STAGING="$(mktemp -d "$DATA/.${NAME}-install-XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT

for project_file in "${FILES[@]}"; do
    stage_file "$project_file"
done

[[ $DEVELOPMENT -eq 1 ]] || chmod 755 "$STAGING/application/$NAME.py" "$STAGING/application/scripts/install-edid.sh" "$STAGING/application/scripts/auto-login.sh"

install -m 644 "$PROJECT_FOLDER/assets/$NAME.png" "$STAGING/icon.png"

sed -E "s#^Exec=.*#Exec=python3 \"$APPLICATION_FOLDER/$NAME.py\"#; s#^Icon=.*#Icon=$ICON#" \
    "$PROJECT_FOLDER/data/$NAME.desktop" > "$STAGING/launcher.desktop"
chmod 644 "$STAGING/launcher.desktop"

mkdir -p "$(dirname "$ICON")" "$(dirname "$LAUNCHER")"
rm -rf "$APPLICATION_FOLDER"
mv "$STAGING/application" "$APPLICATION_FOLDER"
mv -f "$STAGING/icon.png" "$ICON"
mv -f "$STAGING/launcher.desktop" "$LAUNCHER"
rm -f "$OLD_LAUNCHER"

migrate_legacy
remove_legacy
install_command

update_caches

echo "App installed: $APPLICATION_FOLDER"
echo "Icon installed: $ICON"
echo "Launcher installed: $LAUNCHER"
echo "Open it from the menu (Virtual monitor), or run $NAME --help in a terminal."
