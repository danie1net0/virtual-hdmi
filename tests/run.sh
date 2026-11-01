#!/usr/bin/env bash
# Runs all the tests: Python (unittest, no dependencies) and shell scripts.
#
#   bash tests/run.sh
#
# Works on macOS (bash 3.2, BSD tools) and on Linux (bash 5, GNU).

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

failures=0

echo "== Python"
python3 -m unittest discover -s tests -t . || failures=$((failures + 1))

echo "== Shell"
for test in tests/shell/test_*.sh; do
    # Only failures and the summary of each file
    bash "$test" | grep -v -e '^ok ' -e '^# '
    [[ ${PIPESTATUS[0]} -eq 0 ]] || failures=$((failures + 1))
done

if [[ $failures -eq 0 ]]; then
    echo "All ok."
else
    echo "$failures test set(s) failed."
    exit 1
fi
