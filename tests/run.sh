#!/usr/bin/env bash
# Runs all the tests: Python (unittest, no dependencies) and shell scripts, then the mutation gate
# on what changed since origin/master (tests/check-mutations.sh; SKIP_MUTATION=1 leaves it out, as
# the CI test jobs do, since the mutation job runs it).
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

if [[ "${SKIP_MUTATION:-}" != 1 ]]; then
    echo "== Mutation"
    bash tests/check-mutations.sh || failures=$((failures + 1))
fi

if [[ $failures -ne 0 ]]; then
    echo "$failures test set(s) failed."
    exit 1
fi

echo "All ok."
