"""
Mutants of a shell script, line by line, since bash has no parser here.

Each mutant deletes one command (the command lines of tests/shell/shell_coverage.py) or makes one
swap from SWAPS in the code of a line: test operators, && and ||, exit statuses, numbers, options.
Comments stay as they are.
"""

import re

from tests.mutation import Mutant, distinct
from tests.shell import shell_coverage

SWAPS = (
    (r" -eq ", " -ne "),
    (r" -ne ", " -eq "),
    (r" == ", " != "),
    (r" != ", " == "),
    (r" -gt ", " -ge "),
    (r" -ge ", " -gt "),
    (r" -lt ", " -le "),
    (r" -le ", " -lt "),
    (r" < ", " <= "),
    (r" <= ", " < "),
    (r" > ", " >= "),
    (r"\[\[ -z ", "[[ -n "),
    (r"\[\[ -n ", "[[ -z "),
    (r"\[\[ ! ", "[[ "),
    (r"\bif ! ", "if "),
    (r"!(?=[A-Za-z_])", ""),
    (r"\|\|", "&&"),
    (r"&&", "||"),
    (r"\breturn 0\b", "return 1"),
    (r"\breturn 1\b", "return 0"),
    (r"\bexit 0\b", "exit 1"),
    (r"\bexit 1\b", "exit 0"),
    (r"\b1\b", "2"),
    (r"\bcontinue\b", ":"),
    (r"\bnext\b", ""),
    (r" -f ", " -e "),
    (r" -d ", " -e "),
    (r"\^", ""),
    (r"\$\"", '"'),
    (r"-qx", "-q"),
    (r"head -n 1", "cat"),
    (r"tail -1", "cat"),
    (r"sort -u", "cat"),
    (r"echo on ", "echo off "),
    (r"echo off ", "echo on "),
    (r"%%", "%"),
    (r"##", "#"),
)
# A comment starts with a # at the start of a word: ${1##*/} and $# are code
COMMENT = re.compile(r"(^|\s)#")


def code_end(line):
    """Where the code of the line ends: at its comment, or at the line end."""
    found = COMMENT.search(line)
    if found is None:
        return len(line)

    return found.start()


def deletion(path, lines, start, span):
    mutated = list(lines)
    for number in span:
        mutated[number - 1] = ""

    mutated[start - 1] = ":"
    return Mutant(path, start, "delete command", "\n".join(mutated))


def swaps(path, lines, index):
    line = lines[index]
    end = code_end(line)
    found = []
    for pattern, replacement in SWAPS:
        for match in re.finditer(pattern, line[:end]):
            mutated = list(lines)
            mutated[index] = line[: match.start()] + replacement + line[match.end() :]
            found.append(Mutant(path, index + 1, f"'{match.group(0)}' -> '{replacement}'", "\n".join(mutated)))

    return found


def mutants(root, path):
    """Every mutant of the shell script at path (relative to root)."""
    text = (root / path).read_text()
    lines = text.split("\n")
    commands = shell_coverage.executable_lines(root / path)
    found = [deletion(path, lines, start, span) for start, span in commands.items()]
    found.extend(mutant for index in range(len(lines)) for mutant in swaps(path, lines, index))
    return distinct(found, text)
