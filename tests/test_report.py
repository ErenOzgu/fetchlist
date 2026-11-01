from fetchlist.model import Fetch
from fetchlist.report import github, markdown, summary_line, text


def fetch(**kw):
    base = {
        "file": "a/b.yml",
        "line": 3,
        "kind": "url",
        "ref": "https://e.com/x",
        "status": "unpinned",
        "why": "w",
    }
    return Fetch(**{**base, **kw})


def test_markdown_escapes_pipes_in_the_ref():
    assert "a\\|b" in markdown([fetch(ref="a|b")])


def test_github_levels_and_escaping():
    out = github(
        [fetch(ref="http://e.com/%3Cx%3E\nnext"), fetch(status="verified"), fetch(status="unresolved")]
    ).splitlines()
    assert out[0].startswith("::error file=a/b.yml,line=3,title=fetchlist unpinned::")
    assert "%253Cx%253E%0Anext" in out[0]
    assert out[1].startswith("::warning ") and out[2].startswith("::warning ")


def test_text_shows_the_reason_for_everything_but_pinned_and_the_allowance_instead_when_there_is_one():
    rows = text([fetch(status="pinned"), fetch(line=4), fetch(line=5, allowed="because")]).splitlines()
    assert rows[0] == "a/b.yml"
    assert len(rows) == 1 + 1 + 2 + 2 and rows[-1].strip() == "allowed: because" and rows[-3].strip() == "w"


def test_text_can_be_limited_to_some_statuses():
    assert text([fetch(status="pinned")], only={"unpinned"}) == ""


def test_summary_line_counts_graded_fetches_only():
    line = summary_line([fetch(status="pinned"), fetch(status="info"), fetch(allowed="x")])
    assert line == "2 fetches in 1 files: 1 pinned, 1 unpinned (1 allowed)"
