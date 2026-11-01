import pytest

from fetchlist.util import collect_vars, host_of, image_status, is_loopback, parse_image, substitute

HASH = "a" * 64


@pytest.mark.parametrize(
    ("ref", "parsed"),
    [
        ("alpine", ("docker.io", "alpine", "", "")),
        ("alpine:3.20", ("docker.io", "alpine", "3.20", "")),
        ("myuser/app:1", ("docker.io", "myuser/app", "1", "")),
        ("ghcr.io/o/i:v1", ("ghcr.io", "ghcr.io/o/i", "v1", "")),
        ("localhost:5000/img", ("localhost:5000", "localhost:5000/img", "", "")),
        ("localhost:5000/img:2", ("localhost:5000", "localhost:5000/img", "2", "")),
        (f"alpine:3.20@sha256:{HASH}", ("docker.io", "alpine", "3.20", f"sha256:{HASH}")),
        (
            f"registry.example.com:8443/a/b@sha256:{HASH}",
            ("registry.example.com:8443", "registry.example.com:8443/a/b", "", f"sha256:{HASH}"),
        ),
    ],
)
def test_parse_image(ref, parsed):
    assert parse_image(ref) == parsed


def test_image_status_texts():
    assert image_status(f"alpine@sha256:{HASH}") == ("pinned", "pinned by digest")
    assert (
        image_status("alpine@sha256:abc")[0] == "unpinned"
        and "not a sha256 digest" in image_status("alpine@sha256:abc")[1]
    )
    assert image_status("alpine:latest") == ("unpinned", ":latest changes with every push")
    assert "no tag" in image_status("alpine")[1]
    assert "can be pushed again" in image_status("alpine:3")[1]
    assert image_status("${X}")[0] == "unresolved"
    assert image_status("{{ matrix.image }}")[0] == "unresolved"


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("https://Example.com/a", "example.com"),
        ("https://user:pw@example.com:8443/a", "example.com"),
        ("git@github.com:o/r.git", "github.com"),
        ("ssh://git@host.example/o/r", "host.example"),
        ("https://${HOST}/a", ""),
        ("not a url", ""),
    ],
)
def test_host_of(url, host):
    assert host_of(url) == host


def test_loopback():
    for url in (
        "http://localhost:1/",
        "http://127.0.0.1/",
        "http://127.1.2.3:80/x",
        "http://0.0.0.0:80",
        "http://[::1]:80/",
        "http://host.docker.internal/",
    ):
        assert is_loopback(url), url
    for url in ("https://example.com", "http://10.0.0.1/", "http://localhost.example.com/"):
        assert not is_loopback(url), url


def test_substitute_forms_and_nesting():
    v = {"A": "x", "B": "${A}-y", "C": "${B}-z"}
    assert substitute("$A ${A} $(A) ${{ env.A }}", v) == "x x x x"
    assert substitute("${C}", v) == "x-y-z"
    assert substitute("${MISSING:-fallback} ${MISSING-also}", v) == "fallback also"
    assert substitute("${MISSING:?must be set} $MISSING", v) == "${MISSING:?must be set} $MISSING"
    assert substitute("${A}", {"A": None}) == "${A}"


def test_collect_vars_from_shell_yaml_and_make():
    shell = "export A=1\nB='two words'\nC=\"3\" # note\nENV D=4\n  E=\n"
    assert collect_vars(shell) == {"A": "1", "B": "two words", "C": "3", "D": "4"}
    yaml = "env:\n  IMG: alpine:3 # pinned\n  lower: x\n- TOOL: y\n"
    assert collect_vars(yaml, yaml=True) == {"IMG": "alpine:3", "TOOL": "y"}
    assert collect_vars("IMG := alpine:3\nX ?= 2\nY = 3\n", make=True) == {
        "IMG": "alpine:3",
        "X": "2",
        "Y": "3",
    }


def test_a_name_with_two_values_is_ambiguous_and_with_the_same_value_twice_is_not():
    assert collect_vars("A=1\nA=2\n") == {"A": None}
    assert collect_vars("A=1\nA=1\n") == {"A": "1"}
