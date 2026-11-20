"""Tests of the mutation gate: tests/mutation/gate.py, __main__.py and __init__.py."""

import argparse
import contextlib
import dataclasses
import io
import os
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.mutation import Mutant, distinct, gate, python_mutants, runner, scope, shell_mutants

ROOT = Path(__file__).resolve().parent.parent
FIRST = Mutant("a.py", 1, "first", "x = 2\n")
SECOND = Mutant("a.py", 1, "second", "x = 3\n")


def options(arguments, environment=None):
    with mock.patch.dict(os.environ, environment or {}, clear=True):
        return gate.parser().parse_args(arguments)


def main(arguments, results=None, root=ROOT, failure=None):
    """The gate run without the MUTATION_ variables of the shell, as CI sets them for its own run."""
    output = io.StringIO()
    with contextlib.redirect_stdout(output), mock.patch.dict(os.environ, clear=True):
        with mock.patch.object(runner, "run", return_value=results, side_effect=failure) as run:
            status = gate.main(arguments, root)

    return status, output.getvalue(), run


class DistinctTest(unittest.TestCase):
    def test_keeps_the_first_of_each_text_and_drops_the_original(self):
        same = Mutant("a.py", 2, "same", "x = 2\n")
        original = Mutant("a.py", 3, "original", "x = 1\n")
        self.assertEqual(distinct([FIRST, same, original, SECOND], "x = 1\n"), [FIRST, SECOND])

    def test_a_mutant_does_not_change(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            FIRST.line = 2


class ShardTest(unittest.TestCase):
    def test_reads_index_and_total(self):
        self.assertEqual(gate.shard("0/1"), (0, 1))
        self.assertEqual(gate.shard("3/4"), (3, 4))
        self.assertEqual(gate.shard("12/40"), (12, 40))

    def test_refuses_other_texts(self):
        for text in ("4/4", "5/4", "1", "a/4", "1/4x", "-1/4"):
            with self.subTest(text=text), self.assertRaises(argparse.ArgumentTypeError) as raised:
                gate.shard(text)

            self.assertEqual(str(raised.exception), f"{text} is not a slice like 0/4 (index from 0, below the total)")


class ParserTest(unittest.TestCase):
    def test_defaults(self):
        parsed = options([])
        self.assertEqual(parsed.files, [])
        self.assertEqual(parsed.base, "origin/master")
        self.assertFalse(parsed.all)
        self.assertEqual(parsed.shard, (0, 1))
        self.assertEqual(parsed.jobs, os.cpu_count())

    def test_the_environment_sets_the_defaults(self):
        environment = {"MUTATION_BASE": "abc", "MUTATION_SCOPE": "all", "MUTATION_SHARD": "1/4", "MUTATION_JOBS": "3"}
        parsed = options([], environment)
        self.assertEqual((parsed.base, parsed.all, parsed.shard, parsed.jobs), ("abc", True, (1, 4), 3))
        self.assertFalse(options([], {"MUTATION_SCOPE": "some"}).all)

    def test_options_win_over_the_environment(self):
        environment = {"MUTATION_BASE": "abc", "MUTATION_SHARD": "1/4", "MUTATION_JOBS": "3"}
        parsed = options(["--base", "def", "--all", "--shard", "2/4", "--jobs", "5", "a.py", "b.sh"], environment)
        self.assertEqual((parsed.files, parsed.base, parsed.all, parsed.shard, parsed.jobs), (["a.py", "b.sh"], "def", True, (2, 4), 5))

    def test_each_option_has_help(self):
        helps = {action.dest: action.help for action in gate.parser()._actions}
        self.assertEqual(
            helps,
            {
                "help": "show this help message and exit",
                "files": "files to mutate instead of the changed ones",
                "base": "base revision",
                "all": "mutate every file",
                "shard": "slice of the mutants, like 0/4",
                "jobs": "mutants at once",
            },
        )

    def test_help_names_the_script(self):
        self.assertEqual(gate.parser().prog, "tests/check-mutations.sh")
        self.assertEqual(
            gate.parser().description, "The mutation gate: no mutant may survive in the files that changed since the base revision."
        )


class FilesTest(unittest.TestCase):
    def test_files_given_win(self):
        self.assertEqual(gate.files_to_mutate(options(["--all", "a.py"]), ROOT), ["a.py"])

    def test_all_is_everything(self):
        with mock.patch.object(scope, "changed_files") as changed_files:
            self.assertEqual(gate.files_to_mutate(options(["--all"]), ROOT), scope.everything(ROOT))

        changed_files.assert_not_called()

    def test_the_changed_files_pull_in_what_they_affect(self):
        with mock.patch.object(scope, "changed_files", return_value=["tests/shell/test_get.sh"]) as changed_files:
            self.assertEqual(gate.files_to_mutate(options(["--base", "abc"]), ROOT), ["get.sh", "install.sh"])

        changed_files.assert_called_once_with(ROOT, "abc")

    def test_an_unknown_base_mutates_everything(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), mock.patch.object(scope, "changed_files", return_value=None):
            self.assertEqual(gate.files_to_mutate(options(["--base", "abc"]), ROOT), scope.everything(ROOT))

        self.assertEqual(output.getvalue(), "Mutation: abc is not a known revision, so every file is mutated.\n")


class MutantsOfTest(unittest.TestCase):
    def test_takes_the_slice_of_the_mutants_of_each_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.py").write_text("x = 1 + 2\n")
            (root / "b.sh").write_text("exit 1\n")
            found = [*python_mutants.mutants(root, "a.py"), *shell_mutants.mutants(root, "b.sh")]
            self.assertEqual(len(found), 7)
            self.assertEqual(gate.mutants_of(root, ["a.py", "b.sh"], (0, 1)), found)
            self.assertEqual(gate.mutants_of(root, ["a.py", "b.sh"], (1, 3)), [found[1], found[4]])


class MainTest(unittest.TestCase):
    def test_nothing_to_mutate(self):
        with mock.patch.object(scope, "changed_files", return_value=["README.md"]):
            status, output, run = main(["--base", "abc"])

        self.assertEqual((status, output), (0, "Mutation: nothing to mutate since abc.\n"))
        run.assert_not_called()

    def test_passes_when_no_mutant_survived(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.py").write_text("x = 1\n")
            mutants = python_mutants.mutants(root, "a.py")
            status, output, run = main(["--jobs", "3", "a.py"], [(mutant, runner.KILLED) for mutant in mutants], root)

        self.assertEqual(status, 0)
        self.assertEqual(output, "Mutation of a.py: 2 mutants.\nMutation: 2 mutants, 2 killed, 0 survived, 0 timed out, 0 invalid.\n")
        self.assertEqual(run.call_args.args, (root, mutants, 3))

    def test_reports_on_the_standard_output_as_it_goes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.py").write_text("x = 1\n")
            _status, _output, run = main(["a.py"], [], root)

        self.assertIs(run.call_args.kwargs["report"], gate.say)
        with mock.patch("builtins.print") as printed:
            gate.say("line")

        printed.assert_called_once_with("line", flush=True)

    def test_fails_when_a_mutant_survived(self):
        with mock.patch.object(gate, "mutants_of", return_value=[FIRST, SECOND]):
            status, output, _run = main(["a.py", "b.py"], [(FIRST, runner.KILLED), (SECOND, runner.SURVIVED)])

        self.assertEqual(status, 1)
        self.assertEqual(
            output,
            "Mutation of a.py, b.py: 2 mutants.\n"
            "Mutation: 2 mutants, 1 killed, 1 survived, 0 timed out, 0 invalid.\n"
            "Mutants survived. Add a test that fails on each one, or rewrite the code.\n",
        )

    def test_fails_when_the_unmutated_tests_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.py").write_text("x = 1\n")
            status, output, _run = main(["a.py"], root=root, failure=runner.BaselineFailure("a.py"))

        self.assertEqual(status, 1)
        self.assertEqual(
            output,
            "Mutation of a.py: 2 mutants.\nThe tests of a.py fail without any mutant, so no mutant was tested.\n",
        )

    def test_the_shell_variables_do_not_reach_the_tests(self):
        environment = {"MUTATION_SHARD": "1/2", "MUTATION_JOBS": "7", "MUTATION_SCOPE": "all", "MUTATION_BASE": "abc"}
        with mock.patch.dict(os.environ, environment), tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.py").write_text("x = 1\n")
            _status, output, run = main(["a.py"], [], root)

        self.assertEqual(output.splitlines()[0], "Mutation of a.py: 2 mutants.")
        self.assertEqual(run.call_args.args[2], os.cpu_count())

    def test_the_root_is_the_project(self):
        self.assertEqual(gate.ROOT, ROOT)
        self.assertEqual(gate.main.__defaults__, (ROOT,))


class ModuleTest(unittest.TestCase):
    def test_runs_the_gate_with_the_arguments(self):
        with mock.patch.object(gate, "main", return_value=3) as gate_main, mock.patch.object(sys, "argv", ["mutation", "a.py"]):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_module("tests.mutation", run_name="__main__")

        self.assertEqual(raised.exception.code, 3)
        gate_main.assert_called_once_with(["a.py"])

    def test_an_import_runs_nothing(self):
        with mock.patch.object(gate, "main") as gate_main:
            runpy.run_module("tests.mutation.__main__", run_name="tests.mutation.__main__")

        gate_main.assert_not_called()


if __name__ == "__main__":
    unittest.main()
