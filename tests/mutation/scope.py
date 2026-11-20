"""
Which files the mutation gate mutates, and which tests run against the mutants of each one.

The gate mutates the files that changed since a base revision. A changed test pulls in the code it
tests: a Python test (or tests/snapshots, or a Python helper in tests/) pulls in every Python
source, since the whole Python suite runs in under two seconds; a shell test or its snapshot pulls
in the scripts it tests; tests/shell/lib.sh pulls in every script.
"""

import re
import subprocess
import sys

PYTHON_SOURCES = ("virtual-monitor.py", "virtual_monitor/*.py", "tests/shell/shell_coverage.py", "tests/mutation/*.py")
PYTHON_TESTS = (sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "--failfast")
# The shell tests that run against each script; tests/test_mutation_scope.py checks that it lists
# every script and every shell test
SHELL_TESTS = {
    "get.sh": ("tests/shell/test_get.sh",),
    "install.sh": ("tests/shell/test_install.sh", "tests/shell/test_get.sh"),
    "scripts/auto-login.sh": ("tests/shell/test_auto_login.sh",),
    "scripts/install-edid.sh": ("tests/shell/test_install_edid.sh",),
    "scripts/install-session.sh": ("tests/shell/test_install_session.sh",),
    "scripts/install-xfce.sh": ("tests/shell/test_install_xfce.sh",),
    "scripts/keep-session.sh": ("tests/shell/test_keep_session.sh", "tests/shell/test_install_session.sh"),
    "scripts/set-edid.sh": ("tests/shell/test_set_edid.sh",),
}
SHELL_LIBRARY = "tests/shell/lib.sh"
PYTHON_TEST = re.compile(r"tests/([^/]+\.py|snapshots/.+)")
SHELL_TEST = re.compile(r"tests/shell/(snapshots/)?(?P<name>test_\w+)\.(sh|txt)")


def python_sources(root):
    return sorted({path.relative_to(root).as_posix() for pattern in PYTHON_SOURCES for path in root.glob(pattern)})


def everything(root):
    """Every file the gate can mutate: the Python sources, then the shell scripts."""
    return [*python_sources(root), *SHELL_TESTS]


def test_commands(path):
    """The commands that run the tests against a mutant of path."""
    if path.endswith(".py"):
        return [list(PYTHON_TESTS)]

    return [["bash", test] for test in SHELL_TESTS[path]]


def git(root, *arguments):
    return subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True)


def changed_files(root, base):
    """The files changed since base, untracked ones included; None when git does not know base."""
    if git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").returncode != 0:
        return None

    changed = git(root, "diff", "--name-only", "--diff-filter=d", base).stdout.splitlines()
    untracked = git(root, "ls-files", "--others", "--exclude-standard").stdout.splitlines()
    return [*changed, *untracked]


def shell_test(path):
    """The shell test of path, when path is one or its snapshot; None otherwise."""
    found = SHELL_TEST.fullmatch(path)
    if found is None:
        return None

    return f"tests/shell/{found['name']}.sh"


def affected_by(path, sources):
    if path in sources:
        return [path]

    if PYTHON_TEST.fullmatch(path):
        return [source for source in sources if source.endswith(".py")]

    if path == SHELL_LIBRARY:
        return list(SHELL_TESTS)

    test = shell_test(path)
    return [script for script, tests in SHELL_TESTS.items() if test in tests]


def affected(root, changed):
    """The files to mutate for the changed files, in the order of everything()."""
    sources = everything(root)
    found = {source for path in changed for source in affected_by(path, sources)}
    return [source for source in sources if source in found]
