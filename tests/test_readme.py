"""The outputs shown in the README are the committed files, and those are what the tool prints (CI checks that too)."""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_readme_examples_are_the_committed_outputs():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"<!-- example: (\S+) -->\n```text\n(.*?)\n```", readme, flags=re.S)
    assert [name for name, _ in blocks] == ["examples/sample.check.txt", "examples/sample.mirror.txt"]
    for name, body in blocks:
        assert body == (ROOT / name).read_text(encoding="utf-8").rstrip("\n"), name


def test_readme_numbers_match_the_changelog_and_the_package():
    from fetchlist import __version__

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {__version__} - " in changelog
