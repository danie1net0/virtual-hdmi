#!/usr/bin/env bash
# Measures coverage: Python with coverage.py (lines and branches, .coveragerc requires 100%)
# and shell scripts through xtrace (lines; needs bash 4.1+ and a regular user).
#
#   bash tests/coverage.sh
#
# On macOS, bash 3.2 cannot split the xtrace; run it in a container, for example:
#   docker run --rm -v "$PWD":/p:ro -w /p --user 1000:1000 -e HOME=/tmp python:3.13-slim \
#       bash -c 'pip -q install --user coverage && bash tests/coverage.sh'

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

failures=0
DATA="$(mktemp -d)"
trap 'rm -rf "$DATA"' EXIT

echo "== Python"
if python3 -c 'import coverage' 2> /dev/null; then
    python3 -m coverage run --data-file="$DATA/python" -m unittest discover -s tests -t . 2> /dev/null || failures=$((failures + 1))
    python3 -m coverage report --data-file="$DATA/python" || failures=$((failures + 1))
else
    echo "coverage.py not installed (pip install coverage); skipping."
    failures=$((failures + 1))
fi

echo "== Shell"
if [[ ${BASH_VERSINFO[0]} -lt 4 || "$(id -u)" -eq 0 ]]; then
    echo "Needs bash 4.1+ and a regular user (bash ignores PS4 from the environment as root); see the header."
    failures=$((failures + 1))
else
    export COVERAGE="$DATA/shell"
    : > "$COVERAGE"
    for test in tests/shell/test_*.sh; do
        bash "$test" > /dev/null || { echo "Failed: $test"; failures=$((failures + 1)); }
    done
    python3 tests/shell/shell_coverage.py "$COVERAGE" install.sh scripts/*.sh || failures=$((failures + 1))
fi

exit $((failures > 0))
