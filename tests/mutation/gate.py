"""
The mutation gate: no mutant may survive in the files that changed since the base revision.

Run it through tests/check-mutations.sh, or as python3 -m tests.mutation. The options default to
environment variables, so CI and tests/run.sh set them the same way: MUTATION_BASE (the base
revision, origin/master by default), MUTATION_SCOPE=all (every file), MUTATION_SHARD (one slice of
the mutants, 0/4 to 3/4 for four slices) and MUTATION_JOBS (mutants tested at once).
"""

import argparse
import os
import re
from pathlib import Path

from tests.mutation import python_mutants, runner, scope, shell_mutants

ROOT = Path(__file__).resolve().parent.parent.parent
GENERATORS = {".py": python_mutants.mutants, ".sh": shell_mutants.mutants}
SHARD = re.compile(r"(?P<index>\d+)/(?P<total>\d+)")


def shard(text):
    """(index, total) for "index/total", with 0 <= index < total."""
    found = SHARD.fullmatch(text)
    if found is None or int(found["index"]) >= int(found["total"]):
        raise argparse.ArgumentTypeError(f"{text} is not a slice like 0/4 (index from 0, below the total)")

    return int(found["index"]), int(found["total"])


def parser():
    arguments = argparse.ArgumentParser(prog="tests/check-mutations.sh", description=__doc__.strip().splitlines()[0])
    arguments.add_argument("files", nargs="*", help="files to mutate instead of the changed ones")
    arguments.add_argument("--base", default=os.environ.get("MUTATION_BASE", "origin/master"), help="base revision")
    arguments.add_argument(
        "--all", action="store_true", default=os.environ.get("MUTATION_SCOPE") == "all", help="mutate every file"
    )
    arguments.add_argument(
        "--shard", type=shard, default=os.environ.get("MUTATION_SHARD", "0/1"), help="slice of the mutants, like 0/4"
    )
    arguments.add_argument(
        "--jobs", type=int, default=int(os.environ.get("MUTATION_JOBS", os.cpu_count())), help="mutants at once"
    )
    return arguments


def say(line):
    # CI shows the output as it comes only when each line is flushed
    print(line, flush=True)


def files_to_mutate(options, root):
    if options.files:
        return options.files

    if options.all:
        return scope.everything(root)

    changed = scope.changed_files(root, options.base)
    if changed is None:
        say(f"Mutation: {options.base} is not a known revision, so every file is mutated.")
        return scope.everything(root)

    return scope.affected(root, changed)


def mutants_of(root, files, slice_of_mutants):
    index, total = slice_of_mutants
    found = [mutant for path in files for mutant in GENERATORS[Path(path).suffix](root, path)]
    return found[index::total]


def main(arguments, root=ROOT):
    options = parser().parse_args(arguments)
    files = files_to_mutate(options, root)
    if not files:
        say(f"Mutation: nothing to mutate since {options.base}.")
        return 0

    mutants = mutants_of(root, files, options.shard)
    say(f"Mutation of {', '.join(files)}: {len(mutants)} mutants.")
    try:
        results = runner.run(root, mutants, options.jobs, report=say)
    except runner.BaselineFailure as failure:
        say(f"The tests of {failure} fail without any mutant, so no mutant was tested.")
        return 1

    say(runner.summary(results))
    if any(result == runner.SURVIVED for _mutant, result in results):
        say("Mutants survived. Add a test that fails on each one, or rewrite the code.")
        return 1

    return 0
