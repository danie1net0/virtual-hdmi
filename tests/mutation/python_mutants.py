"""
Mutants of a Python source file, found through its syntax tree.

Each mutant changes one place: a comparison, a boolean or arithmetic operator, a constant, the
condition of an if, or a statement (deleted, or a return that gives None). Docstrings and the
literal text of f-strings stay as they are.
"""

import ast
import copy

from tests.mutation import Mutant, distinct

COMPARISON_SWAPS = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
}
BOOLEAN_SWAPS = {ast.And: ast.Or, ast.Or: ast.And}
OPERATOR_SWAPS = {
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
    ast.Mult: ast.Div,
    ast.Div: ast.Mult,
    ast.FloorDiv: ast.Div,
    ast.Mod: ast.FloorDiv,
    ast.BitOr: ast.BitAnd,
    ast.BitAnd: ast.BitOr,
}
CONSTANT_CHANGES = {
    bool: lambda value: not value,
    int: lambda value: value + 1,
    float: lambda value: value + 1,
    str: lambda value: f"XX{value}XX",
}
# Statements whose deletion breaks the file or only hides a name the tests then miss
KEPT_STATEMENTS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)
DOCUMENTED = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
DESCRIPTION_LENGTH = 30


def parent_map(tree):
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def is_docstring(statement, parents):
    """True for the string that opens a module, class or function."""
    owner = parents.get(statement)
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
        and isinstance(owner, DOCUMENTED)
        and owner.body[0] is statement
    )


def parenthesized(node):
    return f"({ast.unparse(node)})"


def comparison_changes(node, _parents):
    if not isinstance(node, ast.Compare):
        return []

    return [comparison_change(node, index) for index in range(len(node.ops))]


def comparison_change(node, index):
    old = type(node.ops[index])
    new = COMPARISON_SWAPS[old]
    mutated = copy.deepcopy(node)
    mutated.ops[index] = new()
    return node, parenthesized(mutated), f"{old.__name__} -> {new.__name__}"


def boolean_changes(node, _parents):
    if not isinstance(node, ast.BoolOp):
        return []

    old = type(node.op)
    new = BOOLEAN_SWAPS[old]
    changes = [(node, parenthesized(ast.BoolOp(op=new(), values=node.values)), f"{old.__name__} -> {new.__name__}")]
    for index in range(len(node.values)):
        others = node.values[:index] + node.values[index + 1 :]
        changes.append((node, parenthesized(ast.BoolOp(op=node.op, values=others)), f"drop operand {index + 1}"))

    return changes


def not_changes(node, _parents):
    if not isinstance(node, ast.UnaryOp) or not isinstance(node.op, ast.Not):
        return []

    return [(node, parenthesized(node.operand), "drop not")]


def operator_changes(node, _parents):
    if not isinstance(node, ast.BinOp) or type(node.op) not in OPERATOR_SWAPS:
        return []

    old = type(node.op)
    new = OPERATOR_SWAPS[old]
    return [(node, parenthesized(ast.BinOp(left=node.left, op=new(), right=node.right)), f"{old.__name__} -> {new.__name__}")]


def constant_changes(node, parents):
    if not isinstance(node, ast.Constant) or type(node.value) not in CONSTANT_CHANGES:
        return []

    # The literal parts of an f-string have no position of their own before Python 3.12
    if is_docstring(parents.get(node), parents) or isinstance(parents.get(node), ast.JoinedStr):
        return []

    replacement = repr(CONSTANT_CHANGES[type(node.value)](node.value))
    return [(node, replacement, f"{repr(node.value)[:DESCRIPTION_LENGTH]} -> {replacement[:DESCRIPTION_LENGTH]}")]


def if_changes(node, _parents):
    if not isinstance(node, ast.If):
        return []

    return [(node.test, f"(not {parenthesized(node.test)})", "negate if")]


def statement_changes(node, parents):
    if not isinstance(node, ast.stmt) or isinstance(node, KEPT_STATEMENTS) or is_docstring(node, parents):
        return []

    return [(node, "pass", "delete statement")]


def ends_function(node, parents):
    """Deleting the last return of a function already gives None."""
    function = parents.get(node)
    return isinstance(function, FUNCTIONS) and function.body[-1] is node


def return_changes(node, parents):
    # A bare return gives None already; a "return None" mutant of "return None" changes nothing
    if not isinstance(node, ast.Return) or node.value is None or ends_function(node, parents):
        return []

    return [(node, "return None", "return None")]


RULES = (
    comparison_changes,
    boolean_changes,
    not_changes,
    operator_changes,
    constant_changes,
    if_changes,
    statement_changes,
    return_changes,
)


def line_starts(data):
    """The byte offset where each line starts; the syntax tree counts columns in UTF-8 bytes."""
    return [0, *(index + 1 for index, byte in enumerate(data) if byte == ord("\n"))]


def mutant(path, data, starts, change):
    node, replacement, description = change
    start = starts[node.lineno - 1] + node.col_offset
    end = starts[node.end_lineno - 1] + node.end_col_offset
    return Mutant(path, node.lineno, description, (data[:start] + replacement.encode() + data[end:]).decode())


def mutants(root, path):
    """Every mutant of the Python file at path (relative to root)."""
    source = (root / path).read_text()
    tree = ast.parse(source)
    parents = parent_map(tree)
    data = source.encode()
    starts = line_starts(data)
    found = [mutant(path, data, starts, change) for node in ast.walk(tree) for rule in RULES for change in rule(node, parents)]
    return distinct(found, source)
