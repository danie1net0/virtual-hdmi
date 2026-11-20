"""Tests of tests/mutation/shell_mutants.py, which finds the mutants of a shell script."""

import tempfile
import unittest
from pathlib import Path

from tests.mutation import Mutant, shell_mutants

# A line of code and one of the lines its swaps give
SWAPPED = (
    ('[[ "$a" -eq 2 ]]', '[[ "$a" -ne 2 ]]'),
    ('[[ "$a" -ne 2 ]]', '[[ "$a" -eq 2 ]]'),
    ('[[ "$a" == b ]]', '[[ "$a" != b ]]'),
    ('[[ "$a" != b ]]', '[[ "$a" == b ]]'),
    ('[[ "$a" -gt 2 ]]', '[[ "$a" -ge 2 ]]'),
    ('[[ "$a" -ge 2 ]]', '[[ "$a" -gt 2 ]]'),
    ('[[ "$a" -lt 2 ]]', '[[ "$a" -le 2 ]]'),
    ('[[ "$a" -le 2 ]]', '[[ "$a" -lt 2 ]]'),
    ("(( a < 2 ))", "(( a <= 2 ))"),
    ("(( a <= 2 ))", "(( a < 2 ))"),
    ("(( a > 2 ))", "(( a >= 2 ))"),
    ('[[ -z "$a" ]]', '[[ -n "$a" ]]'),
    ('[[ -n "$a" ]]', '[[ -z "$a" ]]'),
    ('[[ ! -e "$a" ]]', '[[ -e "$a" ]]'),
    ("if ! true; then", "if true; then"),
    ("awk '!done'", "awk 'done'"),
    ("true || false", "true && false"),
    ("true && false", "true || false"),
    ("return 0", "return 1"),
    ("return 1", "return 0"),
    ("exit 0", "exit 1"),
    ("exit 1", "exit 0"),
    ("sleep 1", "sleep 2"),
    ("[[ -e a ]] || continue", "[[ -e a ]] || :"),
    ("awk '{ next }'", "awk '{  }'"),
    ('[[ -f "$a" ]]', '[[ -e "$a" ]]'),
    ('[[ -d "$a" ]]', '[[ -e "$a" ]]'),
    ("grep '^a'", "grep 'a'"),
    ('echo $"a"', 'echo "a"'),
    ("grep -qx a", "grep -q a"),
    ("head -n 1 file", "cat file"),
    ("tail -1 file", "cat file"),
    ("sort -u file", "cat file"),
    ("echo on > file", "echo off > file"),
    ("echo off > file", "echo on > file"),
    ('echo "${a%%-*}"', 'echo "${a%-*}"'),
    ('echo "${a##*/}"', 'echo "${a#*/}"'),
)


def mutate(source):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / "sample.sh").write_text(source)
        return shell_mutants.mutants(root, "sample.sh")


def changes(source):
    return [(mutant.line, mutant.description, mutant.text) for mutant in mutate(source)]


class SwapTest(unittest.TestCase):
    def test_each_swap_changes_the_code(self):
        for line, swapped in SWAPPED:
            with self.subTest(line=line):
                mutated = [mutant.text for mutant in mutate(f"#!/usr/bin/env bash\n{line}\n")]
                self.assertIn(f"#!/usr/bin/env bash\n{swapped}\n", mutated)

    def test_each_match_is_one_mutant(self):
        self.assertEqual(
            changes("exit 1 || exit 1\n"),
            [
                (1, "delete command", ":\n"),
                (1, "'||' -> '&&'", "exit 1 && exit 1\n"),
                (1, "'exit 1' -> 'exit 0'", "exit 0 || exit 1\n"),
                (1, "'exit 1' -> 'exit 0'", "exit 1 || exit 0\n"),
                (1, "'1' -> '2'", "exit 2 || exit 1\n"),
                (1, "'1' -> '2'", "exit 1 || exit 2\n"),
            ],
        )

    def test_comments_stay(self):
        self.assertEqual(
            changes("#!/usr/bin/env bash\n# exit 1 here\necho a \\\n    b  # exit 1\nname=\"${1##*/}\"\n"),
            [
                (3, "delete command", "#!/usr/bin/env bash\n# exit 1 here\n:\n\nname=\"${1##*/}\"\n"),
                (5, "delete command", "#!/usr/bin/env bash\n# exit 1 here\necho a \\\n    b  # exit 1\n:\n"),
                (5, "'1' -> '2'", "#!/usr/bin/env bash\n# exit 1 here\necho a \\\n    b  # exit 1\nname=\"${2##*/}\"\n"),
                (5, "'##' -> '#'", "#!/usr/bin/env bash\n# exit 1 here\necho a \\\n    b  # exit 1\nname=\"${1#*/}\"\n"),
            ],
        )

    def test_gives_the_path_and_line_of_each_mutant(self):
        self.assertEqual(mutate("true\nexit 0\n")[2], Mutant("sample.sh", 2, "'exit 0' -> 'exit 1'", "true\nexit 1\n"))


class CodeEndTest(unittest.TestCase):
    def test_the_code_ends_at_the_comment(self):
        self.assertEqual(shell_mutants.code_end("echo a  # note"), 7)
        self.assertEqual(shell_mutants.code_end("# note"), 0)
        self.assertEqual(shell_mutants.code_end("    # note"), 3)

    def test_a_hash_inside_a_word_is_code(self):
        self.assertEqual(shell_mutants.code_end('echo "${1##*/}" $#'), 18)


if __name__ == "__main__":
    unittest.main()
