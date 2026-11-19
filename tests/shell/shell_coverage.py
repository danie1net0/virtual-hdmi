"""
Line coverage of the shell scripts, from the xtrace recorded by the tests
(COVERAGE=file, see lib.sh). Lists the command lines that no test executed.

  python3 tests/shell/shell_coverage.py TRACE_FILE script.sh [script.sh ...]

Not counted: comments, blank lines, heredoc bodies, string or command continuation
with "\\", structure lines (fi, done, esac, ;;, {, }, ), then, do), case patterns
alone on a line (on)) and function headers (name() { or name() (); bash does not record
those lines in the xtrace.
"""

import re
import sys
from pathlib import Path

TRACE = re.compile(r"^\++@@(?P<path>[^:]+):(?P<line>\d+)@@ ")
STRUCTURE = re.compile(r"^\s*(fi|done|esac|;;|\}|\)|then|do|\{)\s*(#.*)?$")
FUNCTION = re.compile(r"^\s*[\w-]+\(\)\s*[{(]\s*$")
HEREDOC = re.compile(r"<<-?\s*'?(\w+)'?")
CASE_PATTERN = re.compile(r"^\s*[^\s()]+\)\s*$")


def quote_state(line, state):
    """Quote state (None, "'" or '"') at the end of the line, starting from state."""
    position = 0
    while position < len(line):
        character = line[position]
        position += 1
        if state is None and character == "#":
            break

        if state is None and character in "'\"":
            state = character
            continue

        if character == state:
            state = None

        # A backslash outside single quotes hides the next character
        if character == "\\" and state != "'":
            position += 1

    return state


def command_start(line, number):
    """number if the line starts a command that bash records in the xtrace; None otherwise."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    if STRUCTURE.match(line) or FUNCTION.match(line) or CASE_PATTERN.match(line):
        return None

    return number


def heredoc_after(heredoc, stripped):
    """The heredoc still open after this line, or None if the line closes it."""
    if stripped == heredoc:
        return None

    return heredoc


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
            heredoc = heredoc_after(heredoc, stripped)
            continue

        inside = quote or continued
        if inside:
            result[command].add(number)

        if not inside:
            command = command_start(line, number)

        if not inside and command:
            result[command] = {number}

        quote = quote_state(line, quote)
        found = HEREDOC.search(line)
        if found and quote is None and not stripped.startswith("#"):
            heredoc = found.group(1)

        # A line continues with "\\" only inside a command; a comment ends at the line end
        continued = command is not None and line.endswith("\\")

    return result


def hits(trace_file):
    found = {}
    for line in Path(trace_file).read_text(errors="replace").splitlines():
        match = TRACE.match(line)
        if match:
            found.setdefault(str(Path(match["path"]).resolve()), set()).add(int(match["line"]))

    return found


def main(command_line_arguments):
    trace, scripts = command_line_arguments[0], [Path(script).resolve() for script in command_line_arguments[1:]]
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
    if covered != total:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
