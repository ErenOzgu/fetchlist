from fetchlist.requirements import scan_requirements

SHA = "1" * 40
HASH = "b" * 64


def scan(text):
    return [(f.ref, f.status, f.line) for f in scan_requirements(text, "requirements.txt")]


def test_exact_ranges_and_bare_names():
    text = "ruff==0.6.1\npytest>=8\nrequests\nflask~=3.0\nnumpy==1.*\nsix===1.16.0\n"
    assert scan(text) == [
        ("ruff==0.6.1", "pinned", 1),
        ("pytest>=8", "unpinned", 2),
        ("requests", "unpinned", 3),
        ("flask~=3.0", "unpinned", 4),
        ("numpy==1.*", "unpinned", 5),
        ("six===1.16.0", "pinned", 6),
    ]


def test_comments_markers_extras_and_continuations():
    text = "# top\nruff[x]==0.6.1 ; python_version >= '3.11'  # why\nflask \\\n  >=3\n\n"
    assert scan(text) == [("ruff[x]==0.6.1", "pinned", 2), ("flask>=3", "unpinned", 3)]


def test_hashes_make_a_requirement_pinned():
    assert scan(f"requests==2.32.3 --hash=sha256:{HASH}\n")[0][1] == "pinned"
    assert scan("--require-hashes\nrequests\n")[0][1] == "pinned"


def test_vcs_and_direct_references():
    text = f"git+https://github.com/o/r.git@{SHA}#egg=r\ngit+https://github.com/o/r.git@main#egg=r\npkg @ https://example.com/p.whl\n"
    got = [(f.status) for f in scan_requirements(text, "r.txt")]
    assert got == ["pinned", "unpinned", "unpinned"]


def test_options_that_are_not_downloads_are_skipped():
    assert scan("-r base.txt\n-c constraints.txt\n-e .\n--no-binary :all:\n") == []


def test_an_index_is_recorded_not_graded():
    found = scan_requirements("--index-url https://pkgs.example.com/simple\nruff==0.6.1\n", "r.txt")
    assert [(f.status, f.host) for f in found] == [
        ("info", "pkgs.example.com"),
        ("pinned", "pkgs.example.com"),
    ]


def test_hashes_pin_a_range_and_a_trailing_comment_does_not_change_the_version():
    assert scan(f"requests>=2 --hash=sha256:{HASH}\n")[0][1] == "pinned"
    assert scan("requests==2.0  # pinned for a reason\n")[0][1] == "pinned"


def test_editable_installs_are_read_for_what_they_fetch():
    got = [
        (f.ref, f.status)
        for f in scan_requirements(
            f"-e git+https://github.com/o/r.git@main#egg=r\n-e git+https://github.com/o/r.git@{SHA}#egg=r\n-e .\n",
            "r.txt",
        )
    ]
    assert [s for _, s in got] == ["unpinned", "pinned"]


def test_a_direct_reference_with_a_commit_or_a_hash_is_pinned():
    text = f"a @ git+https://github.com/o/r.git@{SHA}\nb @ https://example.com/b.whl#sha256={HASH}\nc @ https://example.com/c.whl\n"
    assert [f.status for f in scan_requirements(text, "r.txt")] == ["pinned", "pinned", "unpinned"]
