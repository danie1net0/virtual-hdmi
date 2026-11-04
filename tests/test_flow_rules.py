"""Keeps the control flow flat: no else, elif, conditional expressions or ifs inside ifs.

Python is checked through the AST; shell scripts by keyword, since bash has no parser here.
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


def shell_problems(path):
    problems = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        code = line.split("#", 1)[0]
        if SHELL_ELSE.search(code):
            problems.append(f"{number}: else/elif")
    return problems


class FlowRulesTest(unittest.TestCase):
    def test_python_has_flat_control_flow(self):
        for path in PYTHON:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(python_problems(path), [])

    def test_shell_has_no_else(self):
        for path in SHELL:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(shell_problems(path), [])

    def test_detects_each_problem(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        sample = Path(tmp.name) / "sample"

        sample.write_text("a = 1 if b else 2\nif a:\n    if b:\n        pass\nelse:\n    pass\n")
        problems = sorted(python_problems(sample))

        self.assertEqual(problems, ["1: conditional expression", "2: else", "3: if inside the if of line 2"])

        sample.write_text('if x; then :; else :; fi\nelif y\n# else in a comment\necho "elsewhere"\n')
        self.assertEqual(shell_problems(sample), ["1: else/elif", "2: else/elif"])


if __name__ == "__main__":
    unittest.main()
