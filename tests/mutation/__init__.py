"""
Mutation testing of the project's own code, with the standard library only.

A mutant is a copy of one source file with one small change: a comparison flipped, a statement
deleted, a string replaced. The tests must fail on every mutant. One that passes them survived: it
shows a behavior that no test checks. tests/check-mutations.sh runs the gate on the files changed
since a base revision; `python3 -m tests.mutation --help` lists the options.
"""

import dataclasses


@dataclasses.dataclass(frozen=True)
class Mutant:
    path: str
    line: int
    description: str
    text: str


def distinct(mutants, original):
    """The mutants without repeats (same text) and without those that change nothing."""
    unique = {}
    for mutant in mutants:
        unique.setdefault(mutant.text, mutant)

    return [mutant for text, mutant in unique.items() if text != original]
