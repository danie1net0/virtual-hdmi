#!/usr/bin/env bash
# Mutation gate: no mutant may survive in the files changed since the base revision.
#
#   bash tests/check-mutations.sh [FILE ...]
#
# MUTATION_BASE is the base revision (default: origin/master). Every file is mutated when git does
# not know the base or with MUTATION_SCOPE=all; a changed test pulls in the code it tests (see
# tests/mutation/scope.py). MUTATION_SHARD=0/4 to 3/4 tests one of four slices of the mutants, and
# MUTATION_JOBS how many at once (default: the number of processors).

set -euo pipefail
cd "$(dirname "$0")/.."

exec python3 -m tests.mutation "$@"
