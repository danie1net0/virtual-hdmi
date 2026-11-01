"""
Line coverage of the shell scripts, from the xtrace recorded by the tests
(COVERAGE=file, see lib.sh). Lists the command lines that no test executed.

  python3 tests/shell/shell_coverage.py TRACE_FILE script.sh [script.sh ...]

Not counted: comments, blank lines, heredoc bodies, string or command continuation
with "\\", closers (fi, done, esac, ;;, }, then, else, do) and function headers;
bash does not record those lines in the xtrace.
"""

import re
import sys
from pathlib import Path

TRACE = re.compile(r"^\++@@(?P<path>[^:]+):(?P<line>\d+)@@ ")
STRUCTURE = re.compile(r"^\s*(fi|done|esac|;;|\}|\)|then|else|do|\{)\s*(#.*)?$")
FUNCTION = re.compile(r"^\s*[\w-]+\(\)\s*\{\s*$")
HEREDOC = re.compile(r"<<-?\s*'?(\w+)'?")
CASE_PATTERN = re.compile(r"^\s*[^\s()]+\)\s*$")


def quote_state(line, state):
    """Quote state (None, "'" or '"') at the end of the line, starting from state."""
    escaped = False
    for char in line:
        if escaped:
            escaped = False
        elif char == "\\" and state != "'":
            escaped = True
        elif state is None and char == "#":
            break
        elif state is None and char in "'\"":
            state = char
        elif char == state:
            state = None
    return state


def executable_lines(path):
    """{command line: lines it spans}; a multi-line string counts in any of them."""
    lines = path.read_text().splitlines()
    result = {}
    heredoc = None
    quote = None
    continued = False
    command = None
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if heredoc:
            heredoc = None if stripped == heredoc else heredoc
            continue
        if quote or continued:
            if command:
                result[command].add(number)
        else:
            command = None
            skip = not stripped or stripped.startswith("#") or number == 1
            if not (skip or STRUCTURE.match(line) or FUNCTION.match(line) or CASE_PATTERN.match(line)):
                command = number
                result[number] = {number}
        quote = quote_state(line, quote)
        found = HEREDOC.search(line)
        if found and quote is None and not stripped.startswith("#"):
            heredoc = found.group(1)
        continued = quote is None and line.endswith("\\")
    return result


def hits(trace_file):
    found = {}
    for line in Path(trace_file).read_text(errors="replace").splitlines():
        match = TRACE.match(line)
        if match:
            found.setdefault(str(Path(match["path"]).resolve()), set()).add(int(match["line"]))
    return found


def main(argv):
    trace, scripts = argv[0], [Path(p).resolve() for p in argv[1:]]
    executed = hits(trace)
    total = covered = 0
    for script in scripts:
        lines = executable_lines(script)
        seen = executed.get(str(script), set())
        missing = sorted(number for number, span in lines.items() if not span & seen)
        total += len(lines)
        covered += len(lines) - len(missing)
        text = script.read_text().splitlines()
        print(f"{script.name}: {len(lines) - len(missing)}/{len(lines)} lines")
        for number in missing:
            print(f"   {number}: {text[number - 1].strip()}")
    print(f"TOTAL: {covered}/{total} lines ({100 * covered / max(total, 1):.1f}%)")
    return 0 if covered == total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
