"""CHANGELOG.md, the package version and the CI release job agree with each other."""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from virtual_monitor import __version__

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
HEADING = re.compile(r"^## (v\d+\.\d+\.\d+) \((\d{4}-\d{2}-\d{2})\)$")


def headings():
    return [line for line in CHANGELOG.read_text().splitlines() if line.startswith("## ")]


def release_notes(tag):
    """Runs the awk of the release job in .gitlab-ci.yml, as CI does, and returns the notes it writes."""
    ci = (ROOT / ".gitlab-ci.yml").read_text()
    command = re.search(r"^\s+- (awk .*)$", ci, re.MULTILINE).group(1)
    with tempfile.TemporaryDirectory() as folder:
        subprocess.run(
            ["sh", "-c", f"cp '{CHANGELOG}' CHANGELOG.md && {command}"],
            cwd=folder,
            env={**os.environ, "CI_COMMIT_TAG": tag},
            check=True,
        )
        return (Path(folder) / "release-notes.md").read_text()


class ChangelogTest(unittest.TestCase):
    def test_every_heading_is_a_version_with_date(self):
        for heading in headings():
            with self.subTest(heading=heading):
                self.assertRegex(heading, HEADING)

    def test_newest_first(self):
        versions = [tuple(int(number) for number in HEADING.match(heading).group(1)[1:].split(".")) for heading in headings()]
        self.assertEqual(versions, sorted(versions, reverse=True))

    def test_top_entry_is_the_package_version(self):
        self.assertEqual(HEADING.match(headings()[0]).group(1), f"v{__version__}")


class ReleaseNotesTest(unittest.TestCase):
    def test_notes_are_the_section_of_the_tag(self):
        notes = release_notes("v0.2.0")

        self.assertIn("`get.sh` installs with one line", notes)
        self.assertNotIn("## ", notes)
        self.assertNotIn("First release.", notes)
        self.assertNotIn("asks to keep the new mode", notes)

    def test_unknown_tag_gets_no_notes(self):
        self.assertEqual(release_notes("v9.9.9").strip(), "")


if __name__ == "__main__":
    unittest.main()
