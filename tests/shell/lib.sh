# Common helpers for the shell script tests. Load with: source "$(dirname "$0")/lib.sh"
#
# Each script runs in a sandbox: PATH has only basic tools, and the system commands
# (apt-get, systemctl, loginctl, update-grub...) are replaced by stubs that record
# the call in $CALLS. System files live under $ROOT (the scripts' ROOT variable).
#
# COVERAGE=file records the executed lines (bash 4.1+, regular user): see shell_coverage.py.

set -uo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
BIN="$TMP/bin"
FAILURES=0
TOTAL=0

TOOLS=(bash sh cat sed grep awk tail head mkdir install chmod cp mv rm ln ls dirname basename mktemp tr wc env touch sort cmp)
mkdir -p "$BIN"
for tool in "${TOOLS[@]}"; do
    ln -s "$(command -v "$tool")" "$BIN/$tool"
done

# Starts a new case: empty root, stubs and call log
new_case() {
    CASE="$TMP/case-$((TOTAL + 1))-$RANDOM"
    ROOT="$CASE/root"
    STUBS="$CASE/stubs"
    CALLS="$CASE/calls"
    OUT="$CASE/out"
    ERRS="$CASE/errs"
    mkdir -p "$ROOT" "$STUBS"
    : > "$CALLS"
    # id -u says root (FAKE_UID); id <user> exists (FAKE_USER_EXISTS)
    stub id 'if [[ "$1" == -u ]]; then echo "${FAKE_UID:-0}"; exit 0; fi; [[ "${FAKE_USER_EXISTS:-1}" == 1 ]]'
}

# stub name [body]: creates the command name, which records "name args" in $CALLS and runs the body
stub() {
    local name="$1" body="${2:-exit 0}"
    {
        echo '#!/bin/bash'
        echo "echo \"$name\${*:+ \$*}\" >> \"$CALLS\""
        echo "$body"
    } > "$STUBS/$name"
    chmod +x "$STUBS/$name"
}

# run_script script [args...]: runs in the sandbox; leaves stdout in $OUT, stderr in $ERRS and the exit code in $STATUS
run_script() {
    local script="$1"
    shift
    if [[ -z "${COVERAGE:-}" ]]; then
        ROOT="$ROOT" PATH="$STUBS:$BIN" bash "$script" "$@" > "$OUT" 2> "$ERRS"
        STATUS=$?
        return
    fi

    PS4='+@@${BASH_SOURCE}:${LINENO}@@ ' BASH_XTRACEFD=7 ROOT="$ROOT" PATH="$STUBS:$BIN" \
        bash -x "$script" "$@" > "$OUT" 2> "$ERRS" 7>> "$COVERAGE"
    STATUS=$?
}

record() {
    local description="$1" passed="$2"
    TOTAL=$((TOTAL + 1))
    if [[ "$passed" == 1 ]]; then
        echo "ok    $description"
        return
    fi

    echo "FAIL  $description"
    FAILURES=$((FAILURES + 1))
    show_output
}

# Output of the last run_script, shown under a failure
show_output() {
    [[ -f "${OUT:-}" ]] || return 0
    sed 's/^/      output: /' "$OUT"
    sed 's/^/      errors: /' "$ERRS"
}

# check description command...: passes if the command exits with 0
check() {
    local description="$1"
    shift
    "$@" > /dev/null 2>&1
    record "$description" "$(($? == 0))"
}

status_is() {
    local expected="$1" description="$2"
    if [[ "$STATUS" == "$expected" ]]; then
        record "$description" 1
        return
    fi

    record "$description (status $STATUS, expected $expected)" 0
}

# contains file text description: the file has the text (literal)
contains() {
    check "$3" grep -qF -- "$2" "$1"
}

not_contains() {
    grep -qF -- "$2" "$1" 2> /dev/null
    record "$3" "$(($? != 0))"
}

# called "command args": the stub was called with exactly these arguments
called() {
    check "called: $1" grep -qxF -- "$1" "$CALLS"
}

not_called() {
    grep -q -- "^$1\( \|$\)" "$CALLS"
    record "not called: $1" "$(($? != 0))"
}

summary() {
    echo "$((TOTAL - FAILURES))/$TOTAL ok in $(basename "$0")"
    [[ $FAILURES -eq 0 ]]
}
