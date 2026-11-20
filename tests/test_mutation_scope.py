"""Tests of tests/mutation/scope.py, which picks the files to mutate and the tests of each one."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.mutation import scope

ROOT = Path(__file__).resolve().parent.parent
PYTHON = scope.python_sources(ROOT)
SHELL = list(scope.SHELL_TESTS)


def completed(returncode=0, stdout=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


class SourcesTest(unittest.TestCase):
    def test_python_sources_are_the_code_and_the_test_tools(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for path in (
                "virtual-monitor.py",
                "virtual_monitor/b.py",
                "virtual_monitor/a.py",
                "virtual_monitor/notes.txt",
                "tests/shell/shell_coverage.py",
                "tests/mutation/gate.py",
                "tests/test_sample.py",
                "other.py",
            ):
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_text("")

            self.assertEqual(
                scope.python_sources(root),
                [
                    "tests/mutation/gate.py",
                    "tests/shell/shell_coverage.py",
                    "virtual-monitor.py",
                    "virtual_monitor/a.py",
                    "virtual_monitor/b.py",
                ],
            )

    def test_everything_is_the_python_sources_then_the_scripts(self):
        self.assertEqual(scope.everything(ROOT), [*PYTHON, *SHELL])

    def test_every_script_and_every_shell_test_is_listed(self):
        scripts = {"get.sh", "install.sh", *(path.relative_to(ROOT).as_posix() for path in ROOT.glob("scripts/*.sh"))}
        tests = {path.relative_to(ROOT).as_posix() for path in ROOT.glob("tests/shell/test_*.sh")}
        self.assertEqual(set(scope.SHELL_TESTS), scripts)
        self.assertEqual({test for listed in scope.SHELL_TESTS.values() for test in listed}, tests)


class TestCommandsTest(unittest.TestCase):
    def test_python_runs_the_whole_suite_until_the_first_failure(self):
        self.assertEqual(
            scope.test_commands("virtual_monitor/edid.py"),
            [[sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "--failfast"]],
        )

    def test_a_script_runs_its_shell_tests(self):
        self.assertEqual(
            scope.test_commands("scripts/keep-session.sh"),
            [["bash", "tests/shell/test_keep_session.sh"], ["bash", "tests/shell/test_install_session.sh"]],
        )


class ChangedFilesTest(unittest.TestCase):
    def test_runs_git_in_the_root(self):
        with mock.patch("subprocess.run", return_value=completed()) as run:
            scope.git(ROOT, "status", "--short")

        run.assert_called_once_with(["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True)

    def test_lists_the_changed_and_the_untracked_files(self):
        answers = [completed(), completed(stdout="a.py\nb c.sh\n"), completed(stdout="new.py\n")]
        with mock.patch.object(scope, "git", side_effect=answers) as git:
            self.assertEqual(scope.changed_files(ROOT, "base"), ["a.py", "b c.sh", "new.py"])

        self.assertEqual(
            git.call_args_list,
            [
                mock.call(ROOT, "rev-parse", "--verify", "--quiet", "base^{commit}"),
                mock.call(ROOT, "diff", "--name-only", "--diff-filter=d", "base"),
                mock.call(ROOT, "ls-files", "--others", "--exclude-standard"),
            ],
        )

    def test_an_unknown_base_gives_none(self):
        with mock.patch.object(scope, "git", return_value=completed(returncode=1)) as git:
            self.assertIsNone(scope.changed_files(ROOT, "base"))

        git.assert_called_once()


class AffectedTest(unittest.TestCase):
    def test_a_changed_source_is_mutated(self):
        self.assertEqual(scope.affected(ROOT, ["virtual_monitor/edid.py"]), ["virtual_monitor/edid.py"])
        self.assertEqual(scope.affected(ROOT, ["tests/mutation/gate.py"]), ["tests/mutation/gate.py"])
        self.assertEqual(scope.affected(ROOT, ["scripts/set-edid.sh"]), ["scripts/set-edid.sh"])

    def test_a_python_test_pulls_in_every_python_source(self):
        for path in ("tests/test_cli.py", "tests/fake_gi.py", "tests/snapshots/messages.txt"):
            with self.subTest(path=path):
                self.assertEqual(scope.affected(ROOT, [path]), PYTHON)

    def test_the_shell_library_pulls_in_every_script(self):
        self.assertEqual(scope.affected(ROOT, ["tests/shell/lib.sh"]), SHELL)

    def test_a_shell_test_or_its_snapshot_pulls_in_its_scripts(self):
        self.assertEqual(
            scope.affected(ROOT, ["tests/shell/test_install_session.sh"]),
            ["scripts/install-session.sh", "scripts/keep-session.sh"],
        )
        self.assertEqual(scope.affected(ROOT, ["tests/shell/snapshots/test_get.txt"]), ["get.sh", "install.sh"])

    def test_other_files_pull_in_nothing(self):
        changed = ["README.md", "tests/run.sh", "tests/boot/run.sh", "tests/shell/notes.txt", "tests/other/test_a.py"]
        self.assertEqual(scope.affected(ROOT, changed), [])

    def test_keeps_the_order_of_everything_without_repeats(self):
        changed = ["scripts/set-edid.sh", "virtual_monitor/edid.py", "scripts/set-edid.sh"]
        self.assertEqual(scope.affected(ROOT, changed), ["virtual_monitor/edid.py", "scripts/set-edid.sh"])


class ShellTestTest(unittest.TestCase):
    def test_finds_the_test_of_a_test_or_snapshot(self):
        self.assertEqual(scope.shell_test("tests/shell/test_set_edid.sh"), "tests/shell/test_set_edid.sh")
        self.assertEqual(scope.shell_test("tests/shell/snapshots/test_set_edid.txt"), "tests/shell/test_set_edid.sh")

    def test_other_paths_have_none(self):
        for path in ("tests/shell/lib.sh", "tests/shell/test_set_edid.py", "other/tests/shell/test_a.sh", "tests/shell/test_a.sh.bak"):
            with self.subTest(path=path):
                self.assertIsNone(scope.shell_test(path))


if __name__ == "__main__":
    unittest.main()
