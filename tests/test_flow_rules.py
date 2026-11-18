"""Keeps the control flow flat: no else, elif, conditional expressions or ifs inside ifs.

Python is checked through the AST; shell scripts line by line, since bash has no parser here.
"""

import ast
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sorted([ROOT / "virtual-monitor.py", *ROOT.glob("virtual_monitor/*.py"), *ROOT.glob("tests/**/*.py")])
SHELL = sorted([ROOT / "get.sh", ROOT / "install.sh", *ROOT.glob("scripts/*.sh"), *ROOT.glob("tests/**/*.sh")])
SHELL_ELSE = re.compile(r"(^|[;\s])(else|elif)\b")
# Quoted text and [[ ]] tests, which hold && and || that are not commands
SHELL_QUOTED = re.compile(r"'[^']*'|\"(\\.|[^\"\\])*\"|\[\[.*?\]\]")
SHELL_AND_OR = re.compile(r"&&.*\|\|")
# A shell if has its then on the same line here; awk ifs inside quoted programs have none
SHELL_IF = re.compile(r"(^|[;\s(])if\s.*\bthen\b")
SHELL_FI = re.compile(r"(^|[;\s])fi\b")
SHELL_COMMENT = re.compile(r"(^|\s)#.*")


def python_problems(path):
    problems = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.IfExp):
            problems.append(f"{node.lineno}: conditional expression")

        if isinstance(node, (ast.If, ast.For, ast.While, ast.Try)) and node.orelse:
            problems.append(f"{node.lineno}: else")

        if not isinstance(node, ast.If):
            continue

        nested = [child for statement in node.body for child in ast.walk(statement) if isinstance(child, ast.If)]
        problems.extend(f"{child.lineno}: if inside the if of line {node.lineno}" for child in nested)
    return problems


def shell_code(line):
    """The line without quoted text, [[ ]] tests and the comment."""
    return SHELL_COMMENT.sub("", SHELL_QUOTED.sub("", line))


def shell_problems(path):
    problems = []
    depth = 0
    for number, line in enumerate(path.read_text().splitlines(), 1):
        code = shell_code(line)
        if SHELL_ELSE.search(code):
            problems.append(f"{number}: else/elif")

        if SHELL_AND_OR.search(code):
            problems.append(f"{number}: && then || as an if/else")

        for _ in SHELL_IF.finditer(code):
            depth += 1
            if depth > 1:
                problems.append(f"{number}: if inside an if")

        depth -= len(SHELL_FI.findall(code))
    return problems


class FlowRulesTest(unittest.TestCase):
    def test_python_has_flat_control_flow(self):
        for path in PYTHON:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(python_problems(path), [])

    def test_shell_has_flat_control_flow(self):
        for path in SHELL:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(shell_problems(path), [])

    def test_detects_each_problem(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        sample = Path(temporary.name) / "sample"

        sample.write_text("a = 1 if b else 2\nif a:\n    if b:\n        pass\nelse:\n    pass\n")
        problems = sorted(python_problems(sample))

        self.assertEqual(problems, ["1: conditional expression", "2: else", "3: if inside the if of line 2"])

        sample.write_text('if x; then :; else :; fi\nelif y\n# else in a comment\necho "elsewhere"\n')
        self.assertEqual(shell_problems(sample), ["1: else/elif", "2: else/elif"])

        sample.write_text(
            'test -f a && echo yes || echo no\n'
            '[[ -f a && -f b ]] || exit 1\n'
            'echo "a && b || c"\n'
            'if a; then\n'
            '    if b; then :; fi\n'
            'fi\n'
            'if c; then :; fi\n'
            "awk '{ if (x) { print } }'\n"
        )
        self.assertEqual(shell_problems(sample), ["1: && then || as an if/else", "5: if inside an if"])


if __name__ == "__main__":
    unittest.main()
