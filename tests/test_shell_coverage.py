"""Tests of tests/shell/shell_coverage.py, which measures the line coverage of the shell scripts."""

import contextlib
import importlib.util
import io
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SPECIFICATION = importlib.util.spec_from_file_location("shell_coverage", ROOT / "tests" / "shell" / "shell_coverage.py")
shell_coverage = importlib.util.module_from_spec(SPECIFICATION)
SPECIFICATION.loader.exec_module(shell_coverage)


class QuoteStateTest(unittest.TestCase):
    def test_a_line_without_quotes_keeps_the_state(self):
        self.assertIsNone(shell_coverage.quote_state("echo hello", None))
        self.assertEqual(shell_coverage.quote_state("still inside", "'"), "'")

    def test_an_opened_quote_stays_open(self):
        self.assertEqual(shell_coverage.quote_state("echo 'start", None), "'")
        self.assertEqual(shell_coverage.quote_state('echo "start', None), '"')

    def test_a_closed_quote_ends_the_state(self):
        self.assertIsNone(shell_coverage.quote_state("echo 'a' \"b\"", None))
        self.assertIsNone(shell_coverage.quote_state("end'", "'"))

    def test_a_backslash_escapes_outside_single_quotes(self):
        self.assertIsNone(shell_coverage.quote_state("echo \\' done", None))
        self.assertEqual(shell_coverage.quote_state('inside \\" still', '"'), '"')

    def test_a_backslash_does_not_escape_inside_single_quotes(self):
        self.assertIsNone(shell_coverage.quote_state("a \\' b", "'"))

    def test_a_hash_inside_quotes_is_no_comment(self):
        self.assertIsNone(shell_coverage.quote_state("echo 'a # b' done", None))

    def test_only_quotes_open_a_quote(self):
        self.assertIsNone(shell_coverage.quote_state("echo X done", None))

    def test_a_backslash_hides_one_character(self):
        self.assertEqual(shell_coverage.quote_state("echo \\'' done", None), "'")

    def test_a_comment_ends_the_line(self):
        self.assertIsNone(shell_coverage.quote_state("echo # it's a comment", None))
        self.assertEqual(shell_coverage.quote_state("text # not a comment", "'"), "'")


class CommandStartTest(unittest.TestCase):
    def test_lines_that_bash_does_not_trace(self):
        for line in ("", "   ", "# comment", "fi", "done", "esac", ";;", "}", ")", "then", "do", "{", "fi # end",
                     "name() {", "name() (", "check-session() {", "on)", "*)"):
            with self.subTest(line=line):
                self.assertIsNone(shell_coverage.command_start(line, 5))

    def test_the_shebang_is_a_comment_and_a_first_line_command_counts(self):
        self.assertIsNone(shell_coverage.command_start("#!/usr/bin/env bash", 1))
        self.assertEqual(shell_coverage.command_start("echo first", 1), 1)

    def test_a_command_starts_on_its_line(self):
        self.assertEqual(shell_coverage.command_start("    echo hello", 7), 7)
        self.assertEqual(shell_coverage.command_start("on) echo on ;;", 3), 3)


class HeredocAfterTest(unittest.TestCase):
    def test_the_marker_closes_the_heredoc(self):
        self.assertIsNone(shell_coverage.heredoc_after("EOF", "EOF"))

    def test_other_lines_keep_it_open(self):
        self.assertEqual(shell_coverage.heredoc_after("EOF", "echo EOF"), "EOF")


class ExecutableLinesTest(unittest.TestCase):
    def script(self, text):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "script.sh"
        path.write_text(text)
        return path

    def test_simple_commands(self):
        path = self.script("#!/usr/bin/env bash\n# comment\n\necho one\nif true; then\n    echo two\nfi\n")
        self.assertEqual(shell_coverage.executable_lines(path), {4: {4}, 5: {5}, 6: {6}})

    def test_a_multi_line_string_belongs_to_its_command(self):
        path = self.script("#!/bin/bash\nprogram='\n    { print }\n'\necho after\n")
        self.assertEqual(shell_coverage.executable_lines(path), {2: {2, 3, 4}, 5: {5}})

    def test_a_continued_command_spans_its_lines(self):
        path = self.script("#!/bin/bash\nrun one \\\n    two \\\n    three\necho after\n")
        self.assertEqual(shell_coverage.executable_lines(path), {2: {2, 3, 4}, 5: {5}})

    def test_a_heredoc_body_is_not_counted(self):
        path = self.script("#!/bin/bash\ncat <<'EOF'\nif x; then\nEOF\necho after\n")
        self.assertEqual(shell_coverage.executable_lines(path), {2: {2}, 5: {5}})

    def test_a_heredoc_marker_in_a_comment_or_a_string_opens_nothing(self):
        path = self.script("#!/bin/bash\n# cat <<EOF\necho 'a <<EOF\nb'\necho after\n")
        self.assertEqual(shell_coverage.executable_lines(path), {3: {3, 4}, 5: {5}})

    def test_a_comment_ending_in_a_backslash_continues_nothing(self):
        path = self.script("#!/bin/bash\n# a note \\\necho hi\n")
        self.assertEqual(shell_coverage.executable_lines(path), {3: {3}})

    def test_a_string_continued_inside_a_structure_line_is_not_a_command(self):
        path = self.script("#!/bin/bash\n'\nfi\n")
        self.assertEqual(shell_coverage.executable_lines(path), {2: {2, 3}})


class HitsTest(unittest.TestCase):
    def test_reads_the_traced_lines_of_each_script(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        trace = folder / "trace"
        trace.write_text(f"+@@{folder}/first.sh:3@@ echo\n++@@{folder}/first.sh:5@@ true\nnoise\n+@@{folder}/second.sh:1@@ x\n")

        found = shell_coverage.hits(trace)

        self.assertEqual(found, {str((folder / "first.sh").resolve()): {3, 5}, str((folder / "second.sh").resolve()): {1}})

    def test_bytes_that_are_not_text_do_not_stop_the_reading(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        trace = folder / "trace"
        trace.write_bytes(f"+@@{folder}/first.sh:3@@ echo \xff\n".encode("latin-1"))

        self.assertEqual(shell_coverage.hits(trace), {str((folder / "first.sh").resolve()): {3}})


class MainTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.script = self.folder / "script.sh"
        self.script.write_text("#!/bin/bash\necho one\necho two\n")
        self.trace = self.folder / "trace"

    def run_main(self, command_line_arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = shell_coverage.main(command_line_arguments)

        return code, output.getvalue().splitlines()

    def test_full_coverage(self):
        self.trace.write_text(f"+@@{self.script}:2@@ echo one\n+@@{self.script}:3@@ echo two\n")

        code, lines = self.run_main([str(self.trace), str(self.script)])

        self.assertEqual(code, 0)
        self.assertEqual(lines, ["script.sh: 2/2 lines", "TOTAL: 2/2 lines (100.0%)"])

    def test_missing_lines_are_listed_and_fail(self):
        self.trace.write_text(f"+@@{self.script}:2@@ echo one\n")

        code, lines = self.run_main([str(self.trace), str(self.script)])

        self.assertEqual(code, 1)
        self.assertEqual(lines, ["script.sh: 1/2 lines", "   3: echo two", "TOTAL: 1/2 lines (50.0%)"])

    def test_a_single_line_script(self):
        self.script.write_text("echo one\n")
        self.trace.write_text(f"+@@{self.script}:1@@ echo one\n")

        code, lines = self.run_main([str(self.trace), str(self.script)])

        self.assertEqual(code, 0)
        self.assertEqual(lines, ["script.sh: 1/1 lines", "TOTAL: 1/1 lines (100.0%)"])

    def test_no_scripts(self):
        self.trace.write_text("")

        code, lines = self.run_main([str(self.trace)])

        self.assertEqual(code, 0)
        self.assertEqual(lines, ["TOTAL: 0/0 lines (0.0%)"])

    def test_runs_as_a_script(self):
        self.trace.write_text(f"+@@{self.script}:2@@ echo one\n")
        command_line_arguments = ["shell_coverage.py", str(self.trace), str(self.script)]

        with mock.patch.object(sys, "argv", command_line_arguments), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(ROOT / "tests" / "shell" / "shell_coverage.py"), run_name="__main__")

        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
