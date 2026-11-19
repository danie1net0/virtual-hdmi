#!/usr/bin/env bash
# Tests scripts/auto-login.sh with the system root in a temporary folder.
source "$(dirname "$0")/lib.sh"

SCRIPT="$PROJECT/scripts/auto-login.sh"

# A system whose display-manager.service points to the unit $1, with a Wayland and an X11 session
manager() {
    new_case
    mkdir -p "$ROOT/etc/systemd/system" "$ROOT/usr/share/wayland-sessions" "$ROOT/usr/share/xsessions"
    ln -s "/lib/systemd/system/$1.service" "$ROOT/etc/systemd/system/display-manager.service"
    printf '[Desktop Entry]\nName=Plasma\nExec=/usr/bin/startplasma-wayland\n' > "$ROOT/usr/share/wayland-sessions/plasma.desktop"
    printf '[Desktop Entry]\nName=Xfce\nExec=startxfce4\n' > "$ROOT/usr/share/xsessions/xfce.desktop"
    stub gpasswd
}

echo "# arguments"
manager gdm3
FAKE_UID=1000 run_script "$SCRIPT" daniel
status_is 1 "fails without root"
contains "$ERRORS" "Run with sudo." "asks for sudo"

manager gdm3
run_script "$SCRIPT"
status_is 1 "fails without a user"
contains "$ERRORS" "Give the user" "asks for the user"

manager gdm3
run_script "$SCRIPT" 'Daniel; rm -rf /'
status_is 1 "refuses an invalid user name"

manager gdm3
run_script "$SCRIPT" 1daniel
status_is 1 "refuses a user name that starts with a digit"

manager gdm3
run_script "$SCRIPT" daniel maybe
status_is 1 "refuses a state other than on or off"
contains "$ERRORS" "Use on or off, not maybe." "says which states it takes"

manager gdm3
FAKE_USER_EXISTS=0 run_script "$SCRIPT" ghost
status_is 1 "refuses a user that does not exist"
contains "$ERRORS" "User ghost does not exist." "names the missing user"

echo "# GDM"
manager gdm3
mkdir -p "$ROOT/etc/gdm3"
printf '# GDM configuration\n[daemon]\nWaylandEnable=true\nAutomaticLoginEnable = false\n[security]\n' > "$ROOT/etc/gdm3/custom.conf"
run_script "$SCRIPT" daniel
status_is 0 "turns GDM auto-login on"
check "enables the automatic login under [daemon]" test "$(sed -n '/^\[daemon\]/{n;p;}' "$ROOT/etc/gdm3/custom.conf")" = "AutomaticLoginEnable=true"
check "sets the user" grep -qx "AutomaticLogin=daniel" "$ROOT/etc/gdm3/custom.conf"
check "drops the old setting" test "$(grep -c '^AutomaticLoginEnable' "$ROOT/etc/gdm3/custom.conf")" = 1
check "keeps the other settings" grep -qx "WaylandEnable=true" "$ROOT/etc/gdm3/custom.conf"
check "keeps the other sections" grep -qx "\[security\]" "$ROOT/etc/gdm3/custom.conf"
check "keeps a copy of the original" grep -qx "AutomaticLoginEnable = false" "$ROOT/etc/gdm3/custom.conf.before-auto-login"
contains "$OUTPUT" "Automatic login of daniel: on (gdm3)" "says what it does"
contains "$OUTPUT" "without a password" "warns about the open desktop"
contains "$OUTPUT" "to open it again: sudo systemctl restart display-manager" "says how to open the session again after logging out"

run_script "$SCRIPT" daniel
check "running again does not duplicate the settings" test "$(grep -c '^AutomaticLogin=' "$ROOT/etc/gdm3/custom.conf")" = 1
check "does not overwrite the copy of the original" grep -qx "AutomaticLoginEnable = false" "$ROOT/etc/gdm3/custom.conf.before-auto-login"

run_script "$SCRIPT" daniel off
status_is 0 "turns GDM auto-login off"
check "off removes the settings" test "$(grep -c '^AutomaticLogin' "$ROOT/etc/gdm3/custom.conf")" = 0
check "off keeps [daemon]" grep -qx "\[daemon\]" "$ROOT/etc/gdm3/custom.conf"
not_contains "$OUTPUT" "without a password" "off does not warn"
not_contains "$OUTPUT" "restart display-manager" "off does not mention logging out"

manager gdm
run_script "$SCRIPT" daniel
status_is 0 "creates the GDM configuration when it is missing"
check "uses /etc/gdm on distributions without gdm3" test "$(cat "$ROOT/etc/gdm/custom.conf")" = "$(printf '[daemon]\nAutomaticLoginEnable=true\nAutomaticLogin=daniel')"
check "keeps no copy of a file that did not exist" test ! -e "$ROOT/etc/gdm/custom.conf.before-auto-login"

echo "# SDDM"
manager sddm
run_script "$SCRIPT" daniel
status_is 0 "turns SDDM auto-login on"
check "writes the user and the Wayland session" test "$(cat "$ROOT/etc/sddm.conf.d/virtual-monitor-autologin.conf")" = "$(printf '[Autologin]\nUser=daniel\nSession=plasma')"

run_script "$SCRIPT" daniel off
status_is 0 "turns SDDM auto-login off"
check "off removes the SDDM file" test ! -e "$ROOT/etc/sddm.conf.d/virtual-monitor-autologin.conf"

echo "# LightDM"
manager lightdm
rm "$ROOT/usr/share/wayland-sessions/plasma.desktop"
run_script "$SCRIPT" daniel
status_is 0 "turns LightDM auto-login on"
check "writes the user, no delay and the X11 session" test "$(cat "$ROOT/etc/lightdm/lightdm.conf.d/60-virtual-monitor-autologin.conf")" = "$(printf '[Seat:*]\nautologin-user=daniel\nautologin-user-timeout=0\nautologin-session=xfce')"
not_called gpasswd

manager lightdm
rm "$ROOT/usr/share/wayland-sessions/plasma.desktop" "$ROOT/usr/share/xsessions/xfce.desktop"
printf 'root:x:0:\nautologin:x:975:\n' > "$ROOT/etc/group"
run_script "$SCRIPT" daniel
status_is 0 "LightDM without sessions"
not_contains "$ROOT/etc/lightdm/lightdm.conf.d/60-virtual-monitor-autologin.conf" "autologin-session" "leaves the session to LightDM"
called "gpasswd -a daniel autologin"

run_script "$SCRIPT" daniel off
status_is 0 "turns LightDM auto-login off"
check "off removes the LightDM file" test ! -e "$ROOT/etc/lightdm/lightdm.conf.d/60-virtual-monitor-autologin.conf"

echo "# greetd (COSMIC)"
manager greetd
mkdir -p "$ROOT/etc/greetd"
printf '[terminal]\nvt = 1\n\n[general]\nservice = "cosmic-greeter"\n\n[default_session]\ncommand = "cosmic-comp cosmic-greeter"\nuser = "cosmic-greeter"\n' > "$ROOT/etc/greetd/cosmic-greeter.toml"
echo "old" > "$ROOT/etc/greetd/config.toml"
mkdir -p "$ROOT/etc/pam.d"
printf 'auth required pam_unix.so\nsession required pam_limits.so\nsession required pam_env.so readenv=1\n@include common-session\n' > "$ROOT/etc/pam.d/cosmic-greeter"
stub start-cosmic
run_script "$SCRIPT" daniel
status_is 0 "turns greetd auto-login on"
check "marks the session as graphical in the PAM service of the greeter" test "$(sed -n 4p "$ROOT/etc/pam.d/cosmic-greeter")" = "session optional pam_env.so readenv=0 conffile=/etc/security/virtual-monitor-session.conf"
check "the line goes before pam_systemd's include" test "$(sed -n 5p "$ROOT/etc/pam.d/cosmic-greeter")" = "@include common-session"
check "COSMIC is a Wayland session" grep -qx "XDG_SESSION_TYPE OVERRIDE=wayland" "$ROOT/etc/security/virtual-monitor-session.conf"
check "keeps a copy of the PAM service" test "$(grep -c virtual-monitor "$ROOT/etc/pam.d/cosmic-greeter.before-auto-login")" = 0
check "adds the automatic session with COSMIC" test "$(tail -n 3 "$ROOT/etc/greetd/cosmic-greeter.toml")" = "$(printf '[initial_session]\ncommand = "start-cosmic"\nuser = "daniel"')"
check "keeps the greeter session" grep -qx 'user = "cosmic-greeter"' "$ROOT/etc/greetd/cosmic-greeter.toml"
check "keeps a copy of the greetd file" test "$(grep -c initial_session "$ROOT/etc/greetd/cosmic-greeter.toml.before-auto-login")" = 0
check "edits the COSMIC file, not config.toml" grep -qx "old" "$ROOT/etc/greetd/config.toml"
contains "$OUTPUT" "to open it again: sudo rm -f /run/greetd.run && sudo systemctl restart display-manager" "greetd opens the session again only without its runfile"

run_script "$SCRIPT" daniel
check "running again keeps one automatic session" test "$(grep -c '^\[initial_session\]' "$ROOT/etc/greetd/cosmic-greeter.toml")" = 1
check "running again keeps one PAM line" test "$(grep -c virtual-monitor-session "$ROOT/etc/pam.d/cosmic-greeter")" = 1

run_script "$SCRIPT" daniel off
status_is 0 "turns greetd auto-login off"
not_contains "$ROOT/etc/greetd/cosmic-greeter.toml" "initial_session" "off removes the automatic session"
check "off keeps the rest" grep -qx "\[default_session\]" "$ROOT/etc/greetd/cosmic-greeter.toml"
check "off removes the PAM line" test "$(cat "$ROOT/etc/pam.d/cosmic-greeter")" = "$(cat "$ROOT/etc/pam.d/cosmic-greeter.before-auto-login")"
check "off removes the session type file" test ! -e "$ROOT/etc/security/virtual-monitor-session.conf"

manager cosmic-greeter
mkdir -p "$ROOT/etc/greetd"
printf '[default_session]\ncommand = "agreety"\n# [initial_session] logs in once per boot\n\n[initial_session]\ncommand = "old [session]"\nuser = "someone"\n[terminal] # comes after [initial_session]\nvt = 2\n' > "$ROOT/etc/greetd/config.toml"
printf '[Desktop Entry]\nName=Plasma\nTryExec=/usr/bin/plasma-check\nExec=/usr/bin/startplasma-wayland\n\n[Desktop Action Safe]\nExec=/usr/bin/startplasma-safe\n' > "$ROOT/usr/share/wayland-sessions/plasma.desktop"
run_script "$SCRIPT" daniel
status_is 0 "greetd without COSMIC uses the first session"
check "replaces the old automatic session" test "$(grep -c 'someone' "$ROOT/etc/greetd/config.toml")" = 0
check "drops the old command, which has brackets" test "$(grep -c 'old \[session\]' "$ROOT/etc/greetd/config.toml")" = 0
check "keeps a comment that names the table" grep -qx "# \[initial_session\] logs in once per boot" "$ROOT/etc/greetd/config.toml"
check "the automatic session runs the one Exec line of the entry, not TryExec or an action" test "$(sed -n '/^\[initial_session\]/,$p' "$ROOT/etc/greetd/config.toml")" = "$(printf '%s\n' '[initial_session]' 'command = "/usr/bin/startplasma-wayland"' 'user = "daniel"')"
check "keeps the table after the old session" grep -qx "vt = 2" "$ROOT/etc/greetd/config.toml"
check "runs the Exec of the Wayland session" grep -qx 'command = "/usr/bin/startplasma-wayland"' "$ROOT/etc/greetd/config.toml"
contains "$OUTPUT" "no $ROOT/etc/pam.d/greetd" "without the PAM service of greetd, says the type stays"

manager greetd
mkdir -p "$ROOT/etc/greetd" "$ROOT/etc/pam.d"
printf '[terminal] # not [general]\nrunfile = "/run/terminal.run"\n\n[general]\n#runfile = "/run/commented.run"\n# the runfile makes greetd skip [initial_session]\nrunfile = "/var/run/greetd-custom.run"\n\n[default_session]\n' > "$ROOT/etc/greetd/config.toml"
printf '#%%PAM-1.0\nauth include system-login\n# session lines follow\nsession include system-login\n' > "$ROOT/etc/pam.d/greetd"
rm "$ROOT/usr/share/wayland-sessions/plasma.desktop"
run_script "$SCRIPT" daniel
status_is 0 "greetd with only an X11 session"
check "without pam_env, the line goes before the first session line" test "$(cat "$ROOT/etc/pam.d/greetd")" = "$(printf '%s\n' '#%PAM-1.0' 'auth include system-login' '# session lines follow' 'session optional pam_env.so readenv=0 conffile=/etc/security/virtual-monitor-session.conf' 'session include system-login')"
check "an X11 session is marked x11" grep -qx "XDG_SESSION_TYPE OVERRIDE=x11" "$ROOT/etc/security/virtual-monitor-session.conf"
contains "$OUTPUT" "sudo rm -f /var/run/greetd-custom.run &&" "uses the runfile set in the configuration"

manager greetd
mkdir -p "$ROOT/etc/greetd" "$ROOT/etc/pam.d"
echo '[default_session]' > "$ROOT/etc/greetd/config.toml"
printf 'auth required pam_unix.so\n' > "$ROOT/etc/pam.d/greetd"
run_script "$SCRIPT" daniel
check "without session lines, the line goes at the end" test "$(tail -n 1 "$ROOT/etc/pam.d/greetd")" = "session optional pam_env.so readenv=0 conffile=/etc/security/virtual-monitor-session.conf"

manager greetd
mkdir -p "$ROOT/etc/greetd"
echo '[default_session]' > "$ROOT/etc/greetd/config.toml"
rm "$ROOT/usr/share/wayland-sessions/plasma.desktop" "$ROOT/usr/share/xsessions/xfce.desktop"
run_script "$SCRIPT" daniel
status_is 1 "greetd without any session fails"
contains "$ERRORS" "No desktop session found" "says there is no session"
check "fails before touching PAM" test ! -e "$ROOT/etc/security/virtual-monitor-session.conf"

manager greetd
run_script "$SCRIPT" daniel
status_is 1 "greetd without configuration fails"
contains "$ERRORS" "greetd has no configuration" "says the configuration is missing"

echo "# commented and look-alike lines"
manager gdm3
mkdir -p "$ROOT/etc/gdm3"
printf '[daemon]\n# Enabling automatic login\n#  AutomaticLoginEnable = true\n#  AutomaticLogin = user1\n' > "$ROOT/etc/gdm3/custom.conf"
run_script "$SCRIPT" daniel
check "keeps the commented GDM examples" test "$(cat "$ROOT/etc/gdm3/custom.conf")" = "$(printf '%s\n' '[daemon]' 'AutomaticLoginEnable=true' 'AutomaticLogin=daniel' '# Enabling automatic login' '#  AutomaticLoginEnable = true' '#  AutomaticLogin = user1')"

manager gdm3
mkdir -p "$ROOT/etc/gdm3"
printf '# The settings go under [daemon]\n' > "$ROOT/etc/gdm3/custom.conf"
run_script "$SCRIPT" daniel
check "a comment that names [daemon] is not the section" test "$(cat "$ROOT/etc/gdm3/custom.conf")" = "$(printf '%s\n' '# The settings go under [daemon]' '[daemon]' 'AutomaticLoginEnable=true' 'AutomaticLogin=daniel')"

manager lightdm
printf 'noautologin:x:976:\n' > "$ROOT/etc/group"
run_script "$SCRIPT" daniel
status_is 0 "LightDM with a group whose name only ends in autologin"
not_called gpasswd

manager greetd
mkdir -p "$ROOT/etc/greetd" "$ROOT/etc/pam.d"
echo '[default_session]' > "$ROOT/etc/greetd/config.toml"
printf '%s\n' 'auth include system-login' 'session required pam_env.so' '#session optional pam_env.so user_readenv=1' 'session include system-login' > "$ROOT/etc/pam.d/greetd"
run_script "$SCRIPT" daniel
check "the line goes after the last pam_env line, not after a commented one" test "$(cat "$ROOT/etc/pam.d/greetd")" = "$(printf '%s\n' 'auth include system-login' 'session required pam_env.so' 'session optional pam_env.so readenv=0 conffile=/etc/security/virtual-monitor-session.conf' '#session optional pam_env.so user_readenv=1' 'session include system-login')"

echo "# folders with the name of a file"
manager sddm
mkdir -p "$ROOT/usr/share/wayland-sessions/a-folder.desktop"
run_script "$SCRIPT" daniel
check "a folder is no desktop session" grep -qx "Session=plasma" "$ROOT/etc/sddm.conf.d/virtual-monitor-autologin.conf"

manager greetd
mkdir -p "$ROOT/etc/greetd/cosmic-greeter.toml" "$ROOT/etc/pam.d/greetd"
echo '[default_session]' > "$ROOT/etc/greetd/config.toml"
run_script "$SCRIPT" daniel
status_is 0 "greetd with folders where its files go"
check "a folder is no greetd configuration" grep -qx '\[initial_session\]' "$ROOT/etc/greetd/config.toml"
contains "$OUTPUT" "no $ROOT/etc/pam.d/greetd" "a folder is no PAM service"

echo "# unknown display manager"
manager xdm
run_script "$SCRIPT" daniel
status_is 1 "unknown display manager fails"
contains "$ERRORS" "Unknown display manager (xdm)" "names it"

new_case
run_script "$SCRIPT" daniel
status_is 1 "no display manager fails"
contains "$ERRORS" "Unknown display manager (none)" "says there is none"

echo "# failures and the real machine"
manager lightdm
printf 'autologin:x:975:\n' > "$ROOT/etc/group"
stub gpasswd 'exit 1'
run_script "$SCRIPT" daniel
status_is 1 "stops when joining the autologin group fails"

manager gdm3
UNSET_ROOT=1 run_script "$SCRIPT" 'Bad User'
status_is 1 "without ROOT, runs up to the user check"
contains "$ERRORS" "Give the user" "without ROOT, works on /"

summary
