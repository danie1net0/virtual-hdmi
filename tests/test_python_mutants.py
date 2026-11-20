"""Tests of tests/mutation/python_mutants.py, which finds the mutants of a Python file."""

import tempfile
import unittest
from pathlib import Path

from tests.mutation import Mutant, python_mutants


def mutate(source):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / "sample.py").write_text(source)
        return python_mutants.mutants(root, "sample.py")


def changes(source):
    return [(mutant.line, mutant.description, mutant.text) for mutant in mutate(source)]


def described(source, description):
    return [mutant.text for mutant in mutate(source) if mutant.description == description]


class ComparisonTest(unittest.TestCase):
    def test_each_operator_swaps_with_its_opposite(self):
        swaps = (
            ("==", "!=", "Eq -> NotEq"),
            ("!=", "==", "NotEq -> Eq"),
            ("<", "<=", "Lt -> LtE"),
            ("<=", "<", "LtE -> Lt"),
            (">", ">=", "Gt -> GtE"),
            (">=", ">", "GtE -> Gt"),
            ("is", "is not", "Is -> IsNot"),
            ("is not", "is", "IsNot -> Is"),
            ("in", "not in", "In -> NotIn"),
            ("not in", "in", "NotIn -> In"),
        )
        for old, new, description in swaps:
            with self.subTest(old=old):
                self.assertEqual(described(f"x = a {old} b\n", description), [f"x = (a {new} b)\n"])

    def test_a_chain_swaps_one_operator_at_a_time(self):
        self.assertEqual(
            changes("x = a < b < c\n"),
            [
                (1, "delete statement", "pass\n"),
                (1, "Lt -> LtE", "x = (a <= b < c)\n"),
                (1, "Lt -> LtE", "x = (a < b <= c)\n"),
            ],
        )


class BooleanTest(unittest.TestCase):
    def test_swaps_and_or_and_drops_each_operand(self):
        self.assertEqual(
            changes("x = a and b or c\n"),
            [
                (1, "delete statement", "pass\n"),
                (1, "Or -> And", "x = ((a and b) and c)\n"),
                (1, "drop operand 1", "x = (c)\n"),
                (1, "drop operand 2", "x = (a and b)\n"),
                (1, "And -> Or", "x = (a or b) or c\n"),
                (1, "drop operand 1", "x = (b) or c\n"),
                (1, "drop operand 2", "x = (a) or c\n"),
            ],
        )

    def test_drops_not(self):
        self.assertEqual(changes("x = not a\n"), [(1, "delete statement", "pass\n"), (1, "drop not", "x = (a)\n")])

    def test_keeps_the_other_unary_operators(self):
        self.assertEqual(changes("x = -a\n"), [(1, "delete statement", "pass\n")])


class OperatorTest(unittest.TestCase):
    def test_each_operator_swaps(self):
        swaps = (
            ("+", "-", "Add -> Sub"),
            ("-", "+", "Sub -> Add"),
            ("*", "/", "Mult -> Div"),
            ("/", "*", "Div -> Mult"),
            ("//", "/", "FloorDiv -> Div"),
            ("%", "//", "Mod -> FloorDiv"),
            ("|", "&", "BitOr -> BitAnd"),
            ("&", "|", "BitAnd -> BitOr"),
        )
        for old, new, description in swaps:
            with self.subTest(old=old):
                self.assertEqual(
                    changes(f"x = a {old} b\n"), [(1, "delete statement", "pass\n"), (1, description, f"x = (a {new} b)\n")]
                )

    def test_keeps_the_operators_without_a_swap(self):
        self.assertEqual(changes("x = a ** b\n"), [(1, "delete statement", "pass\n")])


class ConstantTest(unittest.TestCase):
    def test_changes_each_kind_of_constant(self):
        self.assertEqual(described("x = True\n", "True -> False"), ["x = False\n"])
        self.assertEqual(described("x = False\n", "False -> True"), ["x = True\n"])
        self.assertEqual(described("x = 1\n", "1 -> 2"), ["x = 2\n"])
        self.assertEqual(described("x = 1.5\n", "1.5 -> 2.5"), ["x = 2.5\n"])
        self.assertEqual(described("x = 'text'\n", "'text' -> 'XXtextXX'"), ["x = 'XXtextXX'\n"])
        self.assertEqual(described("x = ''\n", "'' -> 'XXXX'"), ["x = 'XXXX'\n"])

    def test_keeps_the_other_constants(self):
        self.assertEqual(changes("x = None\ny = b'data'\n"), [(1, "delete statement", "pass\ny = b'data'\n"), (2, "delete statement", "x = None\npass\n")])

    def test_shortens_long_descriptions(self):
        self.assertEqual(
            [mutant.description for mutant in mutate("x = 'a very long string that goes past thirty characters'\n")],
            ["delete statement", "'a very long string that goes  -> 'XXa very long string that goe"],
        )

    def test_counts_columns_in_bytes(self):
        self.assertEqual(
            changes('x = 1\ny = "ção" == z\n'),
            [
                (1, "delete statement", 'pass\ny = "ção" == z\n'),
                (2, "delete statement", "x = 1\npass\n"),
                (1, "1 -> 2", 'x = 2\ny = "ção" == z\n'),
                (2, "Eq -> NotEq", "x = 1\ny = ('ção' != z)\n"),
                (2, "'ção' -> 'XXçãoXX'", "x = 1\ny = 'XXçãoXX' == z\n"),
            ],
        )

    def test_replaces_nodes_over_several_lines(self):
        self.assertEqual(changes("x = (\n    1\n)\n"), [(1, "delete statement", "pass\n"), (2, "1 -> 2", "x = (\n    2\n)\n")])

    def test_keeps_the_text_of_f_strings_but_not_their_values(self):
        self.assertEqual(changes('x = f"a{1}b"\n'), [(1, "delete statement", "pass\n"), (1, "1 -> 2", 'x = f"a{2}b"\n')])


class DocstringTest(unittest.TestCase):
    def test_keeps_the_docstrings(self):
        source = '"""Module."""\n\n\nclass Sample:\n    """Class."""\n\n\ndef first():\n    """Function."""\n\n\nasync def second():\n    """Coroutine."""\n'
        self.assertEqual(changes(source), [])

    def test_changes_strings_that_are_not_docstrings(self):
        self.assertEqual(
            changes('x = 1\n"note"\n'),
            [
                (1, "delete statement", 'pass\n"note"\n'),
                (2, "delete statement", "x = 1\npass\n"),
                (1, "1 -> 2", 'x = 2\n"note"\n'),
                (2, "'note' -> 'XXnoteXX'", "x = 1\n'XXnoteXX'\n"),
            ],
        )
        self.assertEqual(
            changes('if a:\n    "note"\n'),
            [
                (1, "negate if", 'if (not (a)):\n    "note"\n'),
                (1, "delete statement", "pass\n"),
                (2, "delete statement", "if a:\n    pass\n"),
                (2, "'note' -> 'XXnoteXX'", "if a:\n    'XXnoteXX'\n"),
            ],
        )

    def test_a_first_expression_that_is_not_a_string_is_no_docstring(self):
        self.assertEqual(
            changes("def first():\n    1\n"), [(2, "delete statement", "def first():\n    pass\n"), (2, "1 -> 2", "def first():\n    2\n")]
        )
        self.assertEqual(changes("def first():\n    call()\n"), [(2, "delete statement", "def first():\n    pass\n")])


class StatementTest(unittest.TestCase):
    def test_keeps_definitions_and_imports(self):
        self.assertEqual(changes("import os\nfrom os import path\n\n\nclass Sample:\n    pass\n"), [])

    def test_negates_ifs_and_deletes_their_blocks(self):
        self.assertEqual(
            changes("if a:\n    call()\n"),
            [
                (1, "negate if", "if (not (a)):\n    call()\n"),
                (1, "delete statement", "pass\n"),
                (2, "delete statement", "if a:\n    pass\n"),
            ],
        )

    def test_a_pass_has_no_mutant(self):
        self.assertEqual(changes("pass\n"), [])


class ReturnTest(unittest.TestCase):
    def test_an_early_return_gives_none(self):
        self.assertEqual(
            changes("def first():\n    if a:\n        return 1\n    return 2\n"),
            [
                (2, "negate if", "def first():\n    if (not (a)):\n        return 1\n    return 2\n"),
                (2, "delete statement", "def first():\n    pass\n    return 2\n"),
                (4, "delete statement", "def first():\n    if a:\n        return 1\n    pass\n"),
                (3, "delete statement", "def first():\n    if a:\n        pass\n    return 2\n"),
                (3, "return None", "def first():\n    if a:\n        return None\n    return 2\n"),
                (4, "2 -> 3", "def first():\n    if a:\n        return 1\n    return 3\n"),
                (3, "1 -> 2", "def first():\n    if a:\n        return 2\n    return 2\n"),
            ],
        )

    def test_the_last_return_of_a_function_is_only_deleted(self):
        self.assertEqual(described("async def first():\n    return value\n", "return None"), [])
        self.assertEqual(described("def first():\n    return value\n", "return None"), [])

    def test_a_return_that_gives_none_already_stays(self):
        self.assertEqual(described("def first():\n    return\n    call()\n", "return None"), [])
        self.assertEqual(described("def first():\n    return None\n    call()\n", "return None"), [])
        self.assertEqual(
            described("def first():\n    return value\n    call()\n", "return None"),
            ["def first():\n    return None\n    call()\n"],
        )


class MutantsTest(unittest.TestCase):
    def test_gives_the_path_and_line_of_each_mutant(self):
        self.assertEqual(mutate("x = 1\n")[1], Mutant("sample.py", 1, "1 -> 2", "x = 2\n"))

    def test_line_starts_are_byte_offsets(self):
        self.assertEqual(python_mutants.line_starts("é\nab\n".encode()), [0, 3, 6])


if __name__ == "__main__":
    unittest.main()
