"""Tests of tests/mutation/runner.py, which runs the tests against each mutant."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.mutation import Mutant, runner, scope

PASSES = [sys.executable, "-c", "import sample, sys; sys.exit(sample.VALUE != 1)"]
KILLED = Mutant("sample.py", 1, "1 -> 2", "VALUE = 2\n")
SURVIVOR = Mutant("sample.py", 1, "same", "VALUE = 1  # same\n")
BROKEN = Mutant("sample.py", 1, "broken", "VALUE =\n")


def python(code):
    return [sys.executable, "-c", code]


class ProjectTest(unittest.TestCase):
    """A project with one source, sample.py, whose test passes while VALUE is 1."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "sample.py").write_text("VALUE = 1\n")


class PassesTest(ProjectTest):
    def test_passes_when_every_command_passes(self):
        self.assertTrue(runner.passes(self.root, [PASSES, python("")], None))

    def test_stops_at_the_first_failure(self):
        commands = [python("raise SystemExit(1)"), python("open('ran', 'w')")]
        self.assertFalse(runner.passes(self.root, commands, None))
        self.assertFalse((self.root / "ran").exists())

    def test_a_command_past_the_timeout_raises(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            runner.passes(self.root, [python("import time; time.sleep(5)")], 0.2)

    def test_the_commands_write_no_bytecode(self):
        code = "import os, sys; sys.exit(os.environ.get('PYTHONDONTWRITEBYTECODE') != '1')"
        with mock.patch.dict(os.environ):
            os.environ.pop("PYTHONDONTWRITEBYTECODE", None)
            self.assertTrue(runner.passes(self.root, [python(code)], None))

        self.assertEqual(runner.environment()["PATH"], os.environ["PATH"])


class ValidTest(unittest.TestCase):
    def test_python_must_compile(self):
        self.assertIs(runner.is_valid(Mutant("a.py", 1, "", "x = 1\n")), True)
        self.assertIs(runner.is_valid(Mutant("a.py", 1, "", "x =\n")), False)

    def test_shell_must_parse(self):
        self.assertIs(runner.is_valid(Mutant("a.sh", 1, "", "echo a\n")), True)
        self.assertIs(runner.is_valid(Mutant("a.sh", 1, "", "if then\n")), False)


class OutcomeTest(ProjectTest):
    def outcome(self, mutant, commands, timeout=None):
        with mock.patch.object(scope, "test_commands", return_value=commands) as test_commands:
            result = runner.outcome(self.root, mutant, timeout)

        self.assertEqual((self.root / "sample.py").read_text(), "VALUE = 1\n")
        return result, test_commands

    def test_a_mutant_that_fails_the_tests_is_killed(self):
        self.assertEqual(self.outcome(KILLED, [PASSES])[0], runner.KILLED)

    def test_a_mutant_that_passes_them_survived(self):
        self.assertEqual(self.outcome(SURVIVOR, [PASSES])[0], runner.SURVIVED)

    def test_the_tests_run_on_the_mutant(self):
        check = python("import sys; sys.exit(open('sample.py').read() != 'VALUE = 2\\n')")
        result, test_commands = self.outcome(KILLED, [check])
        self.assertEqual(result, runner.SURVIVED)
        test_commands.assert_called_once_with("sample.py")

    def test_a_mutant_that_hangs_timed_out(self):
        self.assertEqual(self.outcome(KILLED, [python("import time; time.sleep(5)")], 0.2)[0], runner.TIMED_OUT)

    def test_an_invalid_mutant_runs_nothing(self):
        result, test_commands = self.outcome(BROKEN, [PASSES])
        self.assertEqual(result, runner.INVALID)
        test_commands.assert_not_called()


class TimeoutsTest(unittest.TestCase):
    COMMANDS = {"a.py": [["python"]], "b.py": [["python"]], "c.sh": [["bash", "c"]]}

    def test_the_unmutated_tests_run_once_per_command_set(self):
        with mock.patch.object(scope, "test_commands", side_effect=self.COMMANDS.get), mock.patch.object(
            runner, "passes", return_value=True
        ) as passes, mock.patch("time.monotonic", side_effect=[0, 3, 10, 17]):
            limits = runner.timeouts(Path("folder"), ["a.py", "b.py", "c.sh"])

        self.assertEqual(limits, {"a.py": 60, "b.py": 60, "c.sh": 70})
        self.assertEqual(
            passes.call_args_list, [mock.call(Path("folder"), [["python"]], None), mock.call(Path("folder"), [["bash", "c"]], None)]
        )

    def test_failing_unmutated_tests_stop_everything(self):
        with mock.patch.object(scope, "test_commands", side_effect=self.COMMANDS.get), mock.patch.object(
            runner, "passes", return_value=False
        ):
            with self.assertRaises(runner.BaselineFailure) as raised:
                runner.timeouts(Path("folder"), ["a.py"])

        self.assertEqual(str(raised.exception), "a.py")


class CopiesTest(ProjectTest):
    def test_copies_the_project_without_git_caches_or_coverage(self):
        for path in (".git/config", "__pycache__/sample.pyc", "tests/__pycache__/a.pyc", ".coverage", ".coverage.1", "tests/a.py"):
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text("")

        (self.root / "link").symlink_to("sample.py")
        with tempfile.TemporaryDirectory() as temporary:
            folders = runner.copies(self.root, Path(temporary), 2)
            self.assertEqual(folders, [Path(temporary) / "0", Path(temporary) / "1"])
            for folder in folders:
                files = sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*"))
                self.assertEqual(files, ["link", "sample.py", "tests", "tests/a.py"])
                self.assertTrue((folder / "link").is_symlink())


class RunTest(ProjectTest):
    def test_tests_every_mutant_and_reports_the_survivors(self):
        lines = []
        with mock.patch.object(scope, "test_commands", return_value=[PASSES]):
            results = runner.run(self.root, [KILLED, SURVIVOR, BROKEN, SURVIVOR], 2, report=lines.append)

        self.assertEqual(
            results, [(KILLED, runner.KILLED), (SURVIVOR, runner.SURVIVED), (BROKEN, runner.INVALID), (SURVIVOR, runner.SURVIVED)]
        )
        self.assertEqual(lines, ["SURVIVED sample.py:1 same", "SURVIVED sample.py:1 same"])

    def test_reports_on_the_standard_output_by_default(self):
        output = io.StringIO()
        with mock.patch.object(scope, "test_commands", return_value=[PASSES]), contextlib.redirect_stdout(output):
            runner.run(self.root, [SURVIVOR], 1)

        self.assertEqual(output.getvalue(), "SURVIVED sample.py:1 same\n")

    def test_failing_unmutated_tests_test_no_mutant(self):
        with mock.patch.object(scope, "test_commands", return_value=[python("raise SystemExit(1)")]):
            with self.assertRaises(runner.BaselineFailure):
                runner.run(self.root, [KILLED], 1, report=self.fail)


class SummaryTest(unittest.TestCase):
    def test_counts_each_outcome(self):
        outcomes = [runner.KILLED, runner.KILLED, runner.KILLED, runner.SURVIVED, runner.SURVIVED, runner.TIMED_OUT, runner.INVALID]
        self.assertEqual(
            runner.summary([(KILLED, outcome) for outcome in outcomes]),
            "Mutation: 7 mutants, 3 killed, 2 survived, 1 timed out, 1 invalid.",
        )


if __name__ == "__main__":
    unittest.main()
