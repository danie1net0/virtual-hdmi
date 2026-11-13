"""Shell scripts must run on macOS bash 3.2 with BSD tools, which CI no longer runs.

CI runs the shell tests on bash 3.2 (Linux, GNU tools), so this test catches what only BSD or bash 4
would show: GNU-only options and bash 4 features.
"""

import re
import tempfile
import unittest
from pathlib import Path

from tests.test_flow_rules import ROOT, SHELL

FORBIDDEN = (
    (re.compile(r"\bsed\b[^;|&]*\s-\w*i"), "sed -i (BSD sed needs a suffix)"),
    (re.compile(r"\binstall\b[^;|&]*\s-\w*D"), "install -D (GNU only)"),
    (re.compile(r"\b(declare|local|typeset)\s+-\w*A"), "associative array (bash 4)"),
    (re.compile(r"\b(mapfile|readarray)\b"), "mapfile/readarray (bash 4)"),
    (re.compile(r"\$\{\w+(,,|\^\^)"), "case conversion (bash 4)"),
)


def portability_problems(path):
    problems = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        code = line.split("#", 1)[0]
        problems.extend(f"{number}: {reason}" for pattern, reason in FORBIDDEN if pattern.search(code))
    return problems


class ShellPortabilityTest(unittest.TestCase):
    def test_scripts_avoid_gnu_only_and_bash_4_features(self):
        for path in SHELL:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(portability_problems(path), [])

    def test_detects_each_problem(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        sample = Path(tmp.name) / "sample.sh"
        sample.write_text(
            "sed -i 's/a/b/' file\n"
            "sed -n -i.bak 's/a/b/' file\n"
            "install -m 644 -D a b\n"
            "declare -A map\n"
            "local -rA map\n"
            "mapfile -t lines < file\n"
            'echo "${name,,} ${name^^}"\n'
            "# sed -i in a comment\n"
            "sed -n 's/a/b/p' file; install -m 644 a b; declare -a list\n"
        )

        self.assertEqual(
            portability_problems(sample),
            [
                "1: sed -i (BSD sed needs a suffix)",
                "2: sed -i (BSD sed needs a suffix)",
                "3: install -D (GNU only)",
                "4: associative array (bash 4)",
                "5: associative array (bash 4)",
                "6: mapfile/readarray (bash 4)",
                "7: case conversion (bash 4)",
            ],
        )


if __name__ == "__main__":
    unittest.main()
