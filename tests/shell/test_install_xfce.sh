#!/usr/bin/env bash
# Tests scripts/install-xfce.sh with apt, debconf and systemctl simulated.
source "$(dirname "$0")/lib.sh"

SCRIPT="$PROJECT/scripts/install-xfce.sh"
AUTOLOGIN="etc/lightdm/lightdm.conf.d/50-autologin-xfce.conf"

# System with apt; the argument lists the polkit agent packages that have a candidate
system() {
    new_case
    local available="$1"
    stub debconf-set-selections 'cat >> "$(dirname "$0")/../debconf"'
    stub apt-get
    stub apt-cache "case \" $available \" in *\" \$2 \"*) echo '  Installed: (none)'; echo '  Candidate: 1.0-1' ;; *) echo '  Installed: (none)'; echo '  Candidate: (none)' ;; esac"
    stub systemctl
}

gdm_autologin() {
    mkdir -p "$ROOT/etc/gdm3"
    printf '[daemon]\nAutomaticLoginEnable = true\nAutomaticLogin = %s\n' "$1" > "$ROOT/etc/gdm3/custom.conf"
}

echo "# user"
system "polkit-gnome"
FAKE_UID=1000 run_script "$SCRIPT" daniel
status_is 1 "fails without root"
contains "$ERRS" "Run with sudo." "asks for sudo"
not_called apt-get

system "polkit-gnome"
run_script "$SCRIPT"
status_is 1 "fails without a user and without GDM"
contains "$ERRS" "Give the user" "asks for the user"

system "polkit-gnome"
mkdir -p "$ROOT/etc/gdm3"
printf '[daemon]\n' > "$ROOT/etc/gdm3/custom.conf"
run_script "$SCRIPT"
status_is 1 "GDM without auto-login fails"

system "polkit-gnome"
FAKE_USER_EXISTS=0 run_script "$SCRIPT" fantasma
status_is 1 "nonexistent user fails"
contains "$ERRS" "User fantasma does not exist." "says which user is missing"
not_called apt-get

system "polkit-gnome"
gdm_autologin daniel
run_script "$SCRIPT"
status_is 0 "uses the GDM auto-login user"
contains "$ROOT/$AUTOLOGIN" "autologin-user=daniel" "configures auto-login for the GDM user"
called "id daniel"

system "polkit-gnome"
gdm_autologin daniel
run_script "$SCRIPT" maria
contains "$ROOT/$AUTOLOGIN" "autologin-user=maria" "the argument beats GDM"

echo "# installation"
system "lxpolkit mate-polkit"
run_script "$SCRIPT" daniel
status_is 0 "instala"
check "debconf picks LightDM" grep -qx "lightdm shared/default-x-display-manager select lightdm" "$CASE/debconf"
called "apt-get update"
called "apt-get install -y --no-install-recommends xfce4 xfce4-terminal xfce4-settings lightdm lightdm-gtk-greeter xserver-xorg xserver-xorg-core x11-xserver-utils dbus-x11"
called "apt-get install -y --no-install-recommends lxpolkit"
not_called "apt-get install -y --no-install-recommends mate-polkit"
contains "$OUT" "polkit agent: lxpolkit" "says which polkit agent it installed"
called "apt-cache policy policykit-1-gnome"
check "stops at the first available agent" test "$(grep -c '^apt-cache' "$CALLS")" = 3
check "XFCE session in the auto-login" grep -qx "autologin-session=xfce" "$ROOT/$AUTOLOGIN"
check "no wait in the auto-login" grep -qx "autologin-user-timeout=0" "$ROOT/$AUTOLOGIN"
check "LightDM is the default manager" grep -qx "/usr/sbin/lightdm" "$ROOT/etc/X11/default-display-manager"
called "systemctl enable --force lightdm.service"

system ""
run_script "$SCRIPT" daniel
status_is 0 "continues without a polkit agent"
contains "$ERRS" "no polkit agent available" "warns that the polkit agent is missing"
check "tries the four agents" test "$(grep -c '^apt-cache' "$CALLS")" = 4
check "installs no agent" test "$(grep -c '^apt-get install' "$CALLS")" = 1

system "policykit-1-gnome"
stub apt-get 'exit 100'
run_script "$SCRIPT" daniel
status_is 100 "apt failure stops the install"
check "does not configure LightDM if apt failed" test ! -e "$ROOT/$AUTOLOGIN"
not_called systemctl

summary
