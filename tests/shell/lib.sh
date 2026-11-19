# Common helpers for the shell script tests. Load with: source "$(dirname "$0")/lib.sh"
#
# Each script runs in a sandbox: PATH has only basic tools, and the system commands
# (apt-get, systemctl, loginctl, update-grub...) are replaced by stubs that record
# the call in $CALLS. System files live under $ROOT (the scripts' ROOT variable).
#
# COVERAGE=file records the executed lines (bash 4.1+, regular user): see shell_coverage.py.

set -uo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPORARY="$(mktemp -d)"
trap 'rm -rf "$TEMPORARY"' EXIT
TOOLS_FOLDER="$TEMPORARY/bin"
FAILURES=0
TOTAL=0
# What every run printed, compared at the end with tests/shell/snapshots/<test file>.txt
SNAPSHOTS="$PROJECT/tests/shell/snapshots"
TRANSCRIPT="$TEMPORARY/transcript"
: > "$TRANSCRIPT"

TOOLS=(bash sh cat sed grep awk tail head mkdir install chmod cp mv rm ln ls dirname basename mktemp tr wc env touch sort cmp readlink)
mkdir -p "$TOOLS_FOLDER"
for tool in "${TOOLS[@]}"; do
    ln -s "$(command -v "$tool")" "$TOOLS_FOLDER/$tool"
done

# Starts a new case: empty root, stubs and call log
new_case() {
    CASE="$TEMPORARY/case-$((TOTAL + 1))-$RANDOM"
    ROOT="$CASE/root"
    STUBS="$CASE/stubs"
    CALLS="$CASE/calls"
    OUTPUT="$CASE/output"
    ERRORS="$CASE/errors"
    mkdir -p "$ROOT" "$STUBS"
    : > "$CALLS"
    # id -u says root (FAKE_UID); id <user> exists (FAKE_USER_EXISTS)
    stub id 'if [[ "$1" == -u ]]; then echo "${FAKE_UID:-0}"; exit 0; fi; [[ "${FAKE_USER_EXISTS:-1}" == 1 ]] && exit 0; echo "id: $1: no such user" >&2; exit 1'
}

# stub name [body]: creates the command name, which records "name arguments" in $CALLS and runs the body
stub() {
    local name="$1" body="${2:-exit 0}"
    {
        echo '#!/bin/bash'
        echo "echo \"$name\${*:+ \$*}\" >> \"$CALLS\""
        echo "$body"
    } > "$STUBS/$name"
    chmod +x "$STUBS/$name"
}

# run_script script [arguments...]: runs in the sandbox; leaves stdout in $OUTPUT, stderr in $ERRORS and the exit code in $STATUS.
# EXTRA_PATH, when set, goes at the end of the sandbox PATH. UNSET_ROOT=1 runs without ROOT, as on
# a real machine (only for runs that stop before writing anything).
run_script() {
    local script="$1" path="$STUBS:$TOOLS_FOLDER${EXTRA_PATH:+:$EXTRA_PATH}" root_setting=(ROOT="$ROOT")
    shift
    [[ -z "${UNSET_ROOT:-}" ]] || root_setting=(-u ROOT)

    if [[ -z "${COVERAGE:-}" ]]; then
        env "${root_setting[@]}" PATH="$path" bash "$script" "$@" > "$OUTPUT" 2> "$ERRORS"
        STATUS=$?
        add_to_transcript "$script" "$@"
        return
    fi

    env "${root_setting[@]}" PS4='+@@${BASH_SOURCE}:${LINENO}@@ ' BASH_XTRACEFD=7 PATH="$path" \
        bash -x "$script" "$@" > "$OUTPUT" 2> "$ERRORS" 7>> "$COVERAGE"
    STATUS=$?
    add_to_transcript "$script" "$@"
}

# add_to_transcript script [arguments...]: the run, its status and output, with the sandbox paths
# replaced by names, so that the transcript is the same on every machine
add_to_transcript() {
    local script="$1"
    shift
    {
        echo "== $(basename "$script")${*:+ $*} (status $STATUS)"
        cat "$OUTPUT"
        echo "-- errors"
        cat "$ERRORS"
    } | sed -e "s#$CASE#CASE#g" -e "s#$TEMPORARY/#TEMPORARY/#g" -e "s#$PROJECT/#PROJECT/#g" >> "$TRANSCRIPT"
}

# The transcript must equal the snapshot; UPDATE_SNAPSHOTS=1 writes the snapshot instead
check_transcript() {
    local snapshot
    snapshot="$SNAPSHOTS/$(basename "$0" .sh).txt"
    [[ "${UPDATE_SNAPSHOTS:-}" != 1 ]] || cp "$TRANSCRIPT" "$snapshot"

    OUTPUT="$TEMPORARY/transcript-difference"
    ERRORS=/dev/null
    diff -u "$snapshot" "$TRANSCRIPT" > "$OUTPUT" 2>&1
    local same=$(($? == 0))
    record "every run printed what tests/shell/snapshots/${snapshot##*/} holds" "$same"
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
    [[ -f "${OUTPUT:-}" ]] || return 0
    sed 's/^/      output: /' "$OUTPUT"
    sed 's/^/      errors: /' "$ERRORS"
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

# called "command arguments": the stub was called with exactly these arguments
called() {
    check "called: $1" grep -qxF -- "$1" "$CALLS"
}

not_called() {
    grep -q -- "^$1\( \|$\)" "$CALLS"
    record "not called: $1" "$(($? != 0))"
}

summary() {
    check_transcript
    echo "$((TOTAL - FAILURES))/$TOTAL ok in $(basename "$0")"
    [[ $FAILURES -eq 0 ]]
}
