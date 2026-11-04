#!/usr/bin/env bash
# Tests get.sh with curl and tar replaced by stubs: tar "extracts" an install.sh that records its call.
source "$(dirname "$0")/lib.sh"

SCRIPT="$PROJECT/get.sh"
ARCHIVE="https://gitlab.com/danie1net0/virtual-hdmi/-/archive"

# stub_download [install.sh exit code]: curl prints the archive, tar writes install.sh into the -C folder
stub_download() {
    local code="${1:-0}"
    stub curl 'echo archive'
    stub tar "cat > /dev/null; mkdir -p \"\$3\"; printf '%s\\n' 'echo \"install.sh\${*:+ \$*}\" >> \"$CALLS\"' 'exit $code' > \"\$3/install.sh\""
}

# Folder tar extracted into, from its recorded call
work_dir() {
    sed -n 's/^tar -xz -C \(.*\) --strip-components=1$/\1/p' "$CALLS"
}

new_case
stub tar
run_script "$SCRIPT"
status_is 1 "fails without curl"
contains "$ERRS" "Missing curl." "says curl is missing"
not_called tar

new_case
stub curl
run_script "$SCRIPT"
status_is 1 "fails without tar"
contains "$ERRS" "Missing tar." "says tar is missing"
not_called curl

new_case
stub_download
VERSION="../evil" run_script "$SCRIPT"
status_is 1 "rejects a VERSION with a path"
contains "$ERRS" "Invalid VERSION: ../evil" "names the invalid VERSION"
not_called curl

new_case
stub_download
run_script "$SCRIPT" --skip-check --dev
status_is 1 "rejects --dev"
contains "$ERRS" "clone the repository" "explains how to use --dev"
not_called curl

new_case
stub_download
run_script "$SCRIPT"
status_is 0 "installs master by default"
called "curl -fsSL $ARCHIVE/master/virtual-hdmi-master.tar.gz"
check "extracts into a temporary folder" test -n "$(work_dir)"
called "install.sh"
check "removes the temporary folder" test ! -e "$(work_dir)"
contains "$OUT" "==> Installing" "says it is installing"

new_case
stub_download
VERSION="v0.2.0" run_script "$SCRIPT" --uninstall
status_is 0 "passes VERSION and the options on"
called "curl -fsSL $ARCHIVE/v0.2.0/virtual-hdmi-v0.2.0.tar.gz"
called "install.sh --uninstall"

new_case
stub_download
stub curl 'exit 22'
run_script "$SCRIPT"
check "a failed download fails" test "$STATUS" -ne 0
not_called install.sh

new_case
stub_download 3
run_script "$SCRIPT"
status_is 3 "returns the status of install.sh"
check "removes the temporary folder after a failure" test ! -e "$(work_dir)"

summary
