"""
Runs the tests against every mutant, each in a copy of the project, and reports what survived.

The unmutated tests run first, once per set of test commands: they must pass, and their time sets
the limit of each mutant run. A mutant that does not even parse (bash -n, compile) is invalid and
runs nothing.
"""

import collections
import concurrent.futures
import os
import queue
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from tests.mutation import scope

KILLED = "killed"
SURVIVED = "survived"
TIMED_OUT = "timed out"
INVALID = "invalid"
OUTCOMES = {True: SURVIVED, False: KILLED}
QUIET = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
IGNORED = shutil.ignore_patterns(".git", "__pycache__", ".coverage*")
# A mutant may make the tests slower, as a loop that waits longer; ten times the unmutated run is a hang
TIMEOUT_FACTOR = 10
MINIMUM_TIMEOUT_SECONDS = 60


class BaselineFailure(Exception):
    """The tests fail without any mutant, so no mutant can be tested."""


def environment():
    # A cached bytecode file of one mutant could stand in for the next one, of the same size
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def passes(folder, commands, timeout):
    """True when every command passes in folder; raises subprocess.TimeoutExpired after timeout."""
    return all(
        subprocess.run(command, cwd=folder, **QUIET, timeout=timeout, env=environment()).returncode == 0
        for command in commands
    )


def compiles(mutant):
    try:
        compile(mutant.text, mutant.path, "exec")
    except SyntaxError:
        return False

    return True


def is_valid(mutant):
    if mutant.path.endswith(".py"):
        return compiles(mutant)

    return subprocess.run(["bash", "-n"], input=mutant.text, **QUIET, text=True).returncode == 0


def tested(folder, commands, timeout):
    try:
        survived = passes(folder, commands, timeout)
    except subprocess.TimeoutExpired:
        return TIMED_OUT

    return OUTCOMES[survived]


def outcome(folder, mutant, timeout):
    """What the tests in folder do with the mutant; folder is left as it was."""
    if not is_valid(mutant):
        return INVALID

    target = folder / mutant.path
    original = target.read_text()
    target.write_text(mutant.text)
    try:
        return tested(folder, scope.test_commands(mutant.path), timeout)
    finally:
        target.write_text(original)


def timeouts(folder, paths):
    """The seconds a mutant of each path may take; raises BaselineFailure when the tests fail."""
    limits = {}
    seconds = {}
    for path in paths:
        commands = scope.test_commands(path)
        key = repr(commands)
        if key not in seconds:
            seconds[key] = baseline_seconds(folder, commands, path)

        limits[path] = max(MINIMUM_TIMEOUT_SECONDS, TIMEOUT_FACTOR * seconds[key])

    return limits


def baseline_seconds(folder, commands, path):
    start = time.monotonic()
    if not passes(folder, commands, None):
        raise BaselineFailure(path)

    return time.monotonic() - start


def copies(root, temporary, count):
    folders = [temporary / str(index) for index in range(count)]
    for folder in folders:
        shutil.copytree(root, folder, symlinks=True, ignore=IGNORED)

    return folders


def run(root, mutants, jobs, report=print):
    """[(mutant, outcome)] in the order of mutants; report gets a line for each survivor."""
    with tempfile.TemporaryDirectory() as temporary:
        folders = copies(root, Path(temporary), jobs)
        limits = timeouts(folders[0], sorted({mutant.path for mutant in mutants}))
        free = queue.Queue()
        for folder in folders:
            free.put(folder)

        def test(mutant):
            folder = free.get()
            try:
                return mutant, outcome(folder, mutant, limits[mutant.path])
            finally:
                free.put(folder)

        results = []
        with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
            for mutant, result in pool.map(test, mutants):
                results.append((mutant, result))
                report_survivor(mutant, result, report)

    return results


def report_survivor(mutant, result, report):
    if result != SURVIVED:
        return

    report(f"SURVIVED {mutant.path}:{mutant.line} {mutant.description}")


def summary(results):
    counts = collections.Counter(result for _mutant, result in results)
    each = ", ".join(f"{counts[result]} {result}" for result in (KILLED, SURVIVED, TIMED_OUT, INVALID))
    return f"Mutation: {len(results)} mutants, {each}."
