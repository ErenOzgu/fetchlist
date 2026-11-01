import pytest

from fetchlist.discover import MAX_BYTES, analyse, classify, local_images


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("Dockerfile", "dockerfile"),
        ("service/Dockerfile", "dockerfile"),
        ("Dockerfile.dev", "dockerfile"),
        ("app.Dockerfile", "dockerfile"),
        ("Containerfile", "dockerfile"),
        ("dockerfile.py", ""),
        ("Dockerfile.md", ""),
        ("docs/dockerfile.txt", ""),
        ("Dockerfile.prod", "dockerfile"),
        (".github/workflows/ci.yml", "workflow"),
        (".github/workflows/ci.yaml", "workflow"),
        (".github/actions/x/action.yml", "workflow"),
        ("action.yml", "workflow"),
        (".gitlab-ci.yml", "gitlab"),
        ("ci/build.gitlab-ci.yml", "gitlab"),
        (".gitlab/ci/test.yml", "gitlab"),
        ("docker-compose.yml", "compose"),
        ("compose.prod.yaml", "compose"),
        ("scripts/install.sh", "script"),
        ("Makefile", "make"),
        ("rules.mk", "make"),
        ("requirements.txt", "requirements"),
        ("requirements-dev.txt", "requirements"),
        ("constraints.txt", "requirements"),
        ("requirements.in", "requirements"),
        ("pom.xml", "pom"),
        ("service/pom.xml", "pom"),
        ("README.md", ""),
        ("src/main.py", ""),
        ("other.yml", ""),
        ("notes/requirements-analysis.md", ""),
    ],
)
def test_classify(path, kind):
    assert classify(path) == kind


def test_directories_that_hold_dependencies_are_not_entered(tmp_path):
    for d in (".git", "node_modules/x", "target", ".venv", "venv", "__pycache__"):
        (tmp_path / d).mkdir(parents=True)
        (tmp_path / d / "Dockerfile").write_text("FROM alpine\n")
    (tmp_path / "Dockerfile").write_text("FROM alpine\n")
    fetches, skips = analyse(tmp_path)
    assert [f.file for f in fetches] == ["Dockerfile"] and skips == []


def test_a_file_over_the_size_limit_is_reported_not_read(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM alpine\n" + "# x\n" * MAX_BYTES)
    fetches, skips = analyse(tmp_path)
    assert fetches == [] and "larger than" in skips[0].reason


def test_a_file_that_is_not_utf8_is_still_read(tmp_path):
    (tmp_path / "Dockerfile").write_bytes(b"# \xff\xfe\nFROM alpine\n")
    assert analyse(tmp_path)[0][0].ref == "alpine"


def test_a_makefile_uses_its_own_variables(tmp_path):
    (tmp_path / "Makefile").write_text("IMG := alpine:3.20\n\nrun:\n\tdocker run --rm $(IMG) true\n")
    found = analyse(tmp_path)[0]
    assert [(f.ref, f.status) for f in found] == [("alpine:3.20", "unpinned")]


def test_a_script_is_scanned_one_paragraph_at_a_time(tmp_path):
    (tmp_path / "s.sh").write_text(
        "curl -O https://example.com/a\nsha256sum -c sums\n\ncurl -O https://example.com/b\n"
    )
    assert [f.status for f in analyse(tmp_path)[0]] == ["verified", "unpinned"]


def test_images_the_file_builds_itself_are_not_downloads(tmp_path):
    (tmp_path / "s.sh").write_text(
        "docker build -t app:ci .\ndocker run --rm app:ci true\ndocker run --rm alpine:3 true\n"
    )
    assert [f.ref for f in analyse(tmp_path)[0]] == ["alpine:3"]
    assert local_images("docker buildx build --tag=x:1 .\nkind load docker-image y:2") == {"x:1", "y:2"}
