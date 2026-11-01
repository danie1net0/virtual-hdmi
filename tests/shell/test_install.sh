#!/usr/bin/env bash
# Tests install.sh with HOME, XDG and caches in a temporary folder.
source "$(dirname "$0")/lib.sh"

SCRIPT="$PROJECT/install.sh"
NAME="virtual-monitor"
LEGACY="monitor-virtual"

# Regular user with its own HOME; python3 with GTK and pkexec present unless the case removes them
user() {
    new_case
    export HOME="$CASE/home"
    mkdir -p "$HOME"
    unset XDG_DATA_HOME XDG_CONFIG_HOME
    DATA="$HOME/.local/share"
    CONFIG="$HOME/.config"
    stub id 'echo 1000'
    stub python3
    stub pkexec
    stub gtk-update-icon-cache
    stub update-desktop-database
}

app() { echo "$DATA/$NAME"; }
icon() { echo "$DATA/icons/hicolor/512x512/apps/$NAME.png"; }
launcher() { echo "$DATA/applications/$NAME.desktop"; }
autostart() { echo "$CONFIG/autostart/$NAME-restore.desktop"; }
mode_file() { echo "$CONFIG/$NAME/mode.json"; }
legacy_app() { echo "$DATA/$LEGACY"; }
legacy_icon() { echo "$DATA/icons/hicolor/512x512/apps/$LEGACY.png"; }
legacy_launcher() { echo "$DATA/applications/$LEGACY.desktop"; }
legacy_autostart() { echo "$CONFIG/autostart/monitor-virtual-restaurar.desktop"; }
legacy_mode_file() { echo "$CONFIG/$LEGACY/modo.json"; }

# Leaves an old Portuguese-named install behind
make_legacy() {
    mkdir -p "$(legacy_app)" "$(dirname "$(legacy_icon)")" "$(dirname "$(legacy_launcher)")" "$CONFIG/autostart"
    echo old > "$(legacy_app)/monitor-virtual.py"
    echo old > "$(legacy_icon)"
    echo old > "$(legacy_launcher)"
    printf '[Desktop Entry]\nType=Application\nExec=python3 "%s/monitor-virtual.py" --restore\n' "$(legacy_app)" > "$(legacy_autostart)"
}

echo "# options"
user
run_script "$SCRIPT" --help
status_is 0 "--help exits with 0"
contains "$OUT" "Virtual monitor installer" "--help shows the help"
run_script "$SCRIPT" -h
status_is 0 "-h exits with 0"
run_script "$SCRIPT" --nothing
status_is 1 "unknown option fails"
contains "$ERRS" "Unknown option: --nothing" "says which option"
run_script "$SCRIPT" --dest-dir
status_is 1 "--dest-dir without a path fails"
run_script "$SCRIPT" --dest-dir --dev
status_is 1 "--dest-dir followed by an option fails"
contains "$ERRS" "--dest-dir needs a path." "explains --dest-dir"

user
stub id 'echo 0'
run_script "$SCRIPT"
status_is 1 "fails as root"
contains "$ERRS" "Run without sudo" "asks to run without sudo"
check "as root installs nothing" test ! -e "$(app)"

echo "# user install"
user
run_script "$SCRIPT"
status_is 0 "installs into ~/.local/share"
check "copies the executable launcher" test -x "$(app)/$NAME.py"
check "copies the executable EDID installer" test -x "$(app)/scripts/install-edid.sh"
for module in "$PROJECT"/virtual_monitor/*.py; do
    check "copies virtual_monitor/$(basename "$module")" cmp "$module" "$(app)/virtual_monitor/$(basename "$module")"
done
check "does not copy tests nor EDIDs" test ! -e "$(app)/tests" -a ! -e "$(app)/edid"
check "does not copy Python caches" test ! -e "$(app)/virtual_monitor/__pycache__"
check "modules are not executable" test ! -x "$(app)/virtual_monitor/displays.py"
check "installs the icon" cmp "$PROJECT/assets/$NAME.png" "$(icon)"
check "launcher points to the app" grep -qx "Exec=python3 \"$(app)/$NAME.py\"" "$(launcher)"
check "launcher points to the icon" grep -qx "Icon=$(icon)" "$(launcher)"
check "launcher keeps the name" grep -qx "Name=Virtual monitor" "$(launcher)"
called "gtk-update-icon-cache -q -t $DATA/icons/hicolor"
called "update-desktop-database $DATA/applications"
called "python3 -c import gi; gi.require_version(\"Gtk\", \"4.0\"); gi.require_version(\"Adw\", \"1\")"
check "leaves no install leftovers" test -z "$(ls -A "$DATA" | grep '^\.virtual-monitor-install')"
check "creates no autostart" test ! -e "$(autostart)"
contains "$OUT" "Open it from the menu" "says how to open it"
if PATH=/usr/bin:/bin command -v python3 > /dev/null; then
    check "installed app works outside the project" env -i PATH=/usr/bin:/bin python3 "$(app)/$NAME.py" --help
fi

echo 'old' > "$(app)/leftover.py"
run_script "$SCRIPT"
status_is 0 "reinstalls over the previous one"
check "reinstall cleans old files" test ! -e "$(app)/leftover.py"

user
export XDG_DATA_HOME="$CASE/data" XDG_CONFIG_HOME="$CASE/config"
DATA="$XDG_DATA_HOME"
run_script "$SCRIPT"
status_is 0 "respects XDG_DATA_HOME"
check "installs into XDG_DATA_HOME" test -f "$(app)/$NAME.py"

user
export XDG_DATA_HOME="relative"
run_script "$SCRIPT"
check "ignores a relative XDG_DATA_HOME" test -f "$HOME/.local/share/$NAME/$NAME.py"
unset XDG_DATA_HOME

user
rm "$STUBS/gtk-update-icon-cache" "$STUBS/update-desktop-database"
run_script "$SCRIPT"
status_is 0 "installs without the cache tools"

user
stub gtk-update-icon-cache 'exit 1'
stub update-desktop-database 'exit 1'
run_script "$SCRIPT"
status_is 0 "cache failure does not stop the install"

echo "# migration from the Portuguese-named install"
user
make_legacy
mkdir -p "$(dirname "$(legacy_mode_file)")"
echo '{"connector": "HDMI-A-1", "mode": "old"}' > "$(legacy_mode_file)"
run_script "$SCRIPT"
status_is 0 "installs over an old install"
check "removes the old app folder" test ! -e "$(legacy_app)"
check "removes the old icon" test ! -e "$(legacy_icon)"
check "removes the old launcher" test ! -e "$(legacy_launcher)"
check "removes the old autostart" test ! -e "$(legacy_autostart)"
check "copies the remembered resolution to mode.json" cmp "$(legacy_mode_file)" "$(mode_file)"
check "keeps the old modo.json" test -f "$(legacy_mode_file)"
check "creates the new autostart with --restore" grep -qx "Exec=python3 \"$(app)/$NAME.py\" --restore" "$(autostart)"
check "new autostart is hidden from menus" grep -qx "NoDisplay=true" "$(autostart)"
contains "$OUT" "Autostart migrated" "says it migrated the autostart"
contains "$OUT" "Migrated: " "says it migrated the resolution"

user
make_legacy
mkdir -p "$(dirname "$(legacy_mode_file)")" "$(dirname "$(mode_file)")"
echo '{"mode": "old"}' > "$(legacy_mode_file)"
echo '{"mode": "new"}' > "$(mode_file)"
run_script "$SCRIPT"
status_is 0 "installs when mode.json already exists"
check "does not overwrite the existing mode.json" grep -q '"new"' "$(mode_file)"

user
mkdir -p "$(dirname "$(legacy_mode_file)")"
echo '{"mode": "old"}' > "$(legacy_mode_file)"
run_script "$SCRIPT"
status_is 0 "installs with only the old modo.json"
check "migrates modo.json without an old autostart" cmp "$(legacy_mode_file)" "$(mode_file)"
check "creates no autostart without an old one" test ! -e "$(autostart)"

user
run_script "$SCRIPT"
status_is 0 "installs with nothing old"
check "creates no mode.json without an old one" test ! -e "$(mode_file)"
check "creates no autostart with nothing old" test ! -e "$(autostart)"

echo "# dependencies"
user
stub python3 'exit 1'
run_script "$SCRIPT"
status_is 1 "fails without GTK 4"
contains "$ERRS" "sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1" "shows the apt install"
check "without GTK installs nothing" test ! -e "$(app)"

user
rm "$STUBS/python3"
run_script "$SCRIPT"
status_is 1 "fails without python3"
contains "$ERRS" "Missing python3." "says python3 is missing"

user
rm "$STUBS/python3"
run_script "$SCRIPT" --skip-check
status_is 0 "--skip-check does not check dependencies"

user
rm "$STUBS/pkexec"
run_script "$SCRIPT"
status_is 0 "installs without pkexec"
contains "$OUT" "Warning: without pkexec" "warns about the missing pkexec"

echo "# --dest-dir and --dev"
user
make_legacy
mkdir -p "$(dirname "$(legacy_mode_file)")"
echo '{}' > "$(legacy_mode_file)"
echo "Exec=existing" > "$(autostart)"
DATA="$CASE/destination"
run_script "$SCRIPT" --skip-check --dest-dir "$CASE/destination"
status_is 0 "installs into --dest-dir"
check "uses --dest-dir" test -x "$(app)/$NAME.py"
check "--dest-dir points the launcher there" grep -qx "Exec=python3 \"$(app)/$NAME.py\"" "$(launcher)"
not_called gtk-update-icon-cache
not_called update-desktop-database
check "--dest-dir leaves the autostart alone" grep -qx "Exec=existing" "$(autostart)"
check "--dest-dir does not migrate modo.json" test ! -e "$(mode_file)"
check "--dest-dir leaves the old autostart" test -f "$CONFIG/autostart/monitor-virtual-restaurar.desktop"
check "--dest-dir leaves the old app of the user" test -d "$HOME/.local/share/$LEGACY"

cd "$CASE" || exit 1
run_script "$SCRIPT" --skip-check --dest-dir relative
cd - > /dev/null || exit 1
status_is 0 "relative --dest-dir"
check "relative --dest-dir becomes absolute in the launcher" grep -qx "Exec=python3 \"$CASE/relative/$NAME/$NAME.py\"" "$CASE/relative/applications/$NAME.desktop"

user
DATA="$CASE/dev"
run_script "$SCRIPT" --skip-check --dev --dest-dir "$DATA"
status_is 0 "installs in dev mode"
check "dev links the launcher" test -L "$(app)/$NAME.py"
check "dev links the modules" test -L "$(app)/virtual_monitor/displays.py"
check "dev points to the project" test "$(readlink "$(app)/virtual_monitor/displays.py" 2>/dev/null || ls -l "$(app)/virtual_monitor/displays.py" | sed 's/.* -> //')" = "$PROJECT/virtual_monitor/displays.py"

copy_project() {
    mkdir -p "$1"
    cp -R "$PROJECT/install.sh" "$PROJECT/$NAME.py" "$PROJECT/virtual_monitor" "$PROJECT/scripts" "$PROJECT/data" "$PROJECT/assets" "$1/"
}

user
copy_project "$CASE/project"
run_script "$CASE/project/install.sh" --skip-check --dest-dir "$CASE/project/out"
status_is 1 "refuses a destination inside the project"
contains "$ERRS" "Destination cannot be inside the project folder." "explains the destination inside the project"
check "does not install inside the project" test ! -e "$CASE/project/out/$NAME"

user
copy_project "$CASE/x/$NAME/sub/project"
run_script "$CASE/x/$NAME/sub/project/install.sh" --skip-check --dest-dir "$CASE/x"
status_is 1 "refuses a destination that contains the project"
contains "$ERRS" "Destination cannot contain the project folder." "explains the destination that contains the project"
check "does not delete the project" test -f "$CASE/x/$NAME/sub/project/install.sh"

echo "# project files"
user
COPY="$CASE/project"
copy_project "$COPY"
rm -r "$COPY/assets"
run_script "$COPY/install.sh" --skip-check
status_is 1 "project without an icon fails"
contains "$ERRS" "Missing file: assets/$NAME.png" "says which file is missing"

echo "# uninstall"
user
run_script "$SCRIPT"
mkdir -p "$CONFIG/autostart" "$CONFIG/$NAME"
echo "x" > "$(autostart)"
echo "{}" > "$(mode_file)"
make_legacy
: > "$CALLS"
run_script "$SCRIPT" --uninstall
status_is 0 "removes everything"
check "app removed" test ! -e "$(app)"
check "icon removed" test ! -e "$(icon)"
check "launcher removed" test ! -e "$(launcher)"
check "autostart removed" test ! -e "$(autostart)"
check "old app removed" test ! -e "$(legacy_app)"
check "old icon removed" test ! -e "$(legacy_icon)"
check "old launcher removed" test ! -e "$(legacy_launcher)"
check "old autostart removed" test ! -e "$(legacy_autostart)"
check "remembered choice stays" test -f "$(mode_file)"
called "update-desktop-database $DATA/applications"
contains "$OUT" "The remembered resolution stays in $CONFIG/$NAME" "says where the choice stayed"

run_script "$SCRIPT" --uninstall
status_is 0 "uninstalling again does not fail"

user
mkdir -p "$CONFIG/autostart"
echo "x" > "$(autostart)"
DATA="$CASE/destination"
run_script "$SCRIPT" --skip-check --dest-dir "$DATA"
run_script "$SCRIPT" --uninstall --dest-dir "$DATA"
status_is 0 "removes from --dest-dir"
check "removes the app from --dest-dir" test ! -e "$(app)"
check "--dest-dir does not remove the user autostart" test -f "$(autostart)"

summary
