from fetchlist.dockerfile import instructions, scan_dockerfile

HASH = "a" * 64


def scan(text):
    return scan_dockerfile(text, "Dockerfile")


def test_from_by_tag_is_unpinned_and_by_digest_is_pinned():
    found = scan(f"FROM python:3.12-slim\nFROM alpine:3.20@sha256:{HASH}\n")
    assert [(f.ref, f.status, f.line) for f in found] == [
        ("python:3.12-slim", "unpinned", 1),
        (f"alpine:3.20@sha256:{HASH}", "pinned", 2),
    ]


def test_no_tag_means_latest():
    f = scan("FROM ubuntu\n")[0]
    assert f.status == "unpinned" and "latest" in f.why


def test_a_stage_name_and_scratch_are_not_downloads():
    text = "FROM golang:1.23 AS build\nRUN true\nFROM scratch\nFROM build AS test\nCOPY --from=build /a /a\nCOPY --from=0 /a /b\n"
    assert [f.ref for f in scan(text)] == ["golang:1.23"]


def test_copy_from_an_external_image_is_a_download():
    f = scan("FROM scratch\nCOPY --from=ghcr.io/o/tool:1.0 /tool /tool\n")[0]
    assert (f.ref, f.status, f.line) == ("ghcr.io/o/tool:1.0", "unpinned", 2)


def test_platform_flag_and_as_are_understood():
    assert scan("FROM --platform=$BUILDPLATFORM node:22 AS web\n")[0].ref == "node:22"


def test_arg_default_before_from_is_used():
    f = scan(f"ARG BASE=python:3.12@sha256:{HASH}\nFROM ${{BASE}}\n")[0]
    assert f.status == "pinned" and f.ref.startswith("python:3.12@")


def test_arg_without_default_is_unresolved():
    f = scan("ARG BASE\nFROM ${BASE}\n")[0]
    assert f.status == "unresolved"


def test_add_from_a_url():
    unpinned = scan("FROM scratch\nADD https://example.com/t.tgz /t.tgz\n")[0]
    assert unpinned.kind == "url" and unpinned.status == "unpinned"
    pinned = scan(f"FROM scratch\nADD --checksum=sha256:{HASH} https://example.com/t.tgz /t.tgz\n")[0]
    assert pinned.status == "pinned"
    assert scan("FROM scratch\nADD local.tgz /x\n") == []


def test_run_is_scanned_as_shell_with_continuations():
    text = (
        "FROM alpine@sha256:"
        + HASH
        + "\nRUN apk add --no-cache curl \\\n && curl -fsSL https://example.com/t -o /t \\\n && chmod +x /t\n"
    )
    found = scan(text)
    assert [(f.kind, f.line) for f in found] == [("image", 1), ("url", 2)]


def test_run_with_a_checksum_in_the_same_instruction_is_pinned():
    text = f"FROM scratch\nRUN curl -fsSLo /t https://example.com/t && echo '{HASH}  /t' | sha256sum -c -\n"
    assert scan(text)[0].status == "pinned"


def test_run_mount_flags_exec_form_and_heredocs():
    text = (
        "FROM scratch\n"
        "RUN --mount=type=cache,target=/root/.cache pip install ruff\n"
        'RUN ["pip", "install", "pytest==8.3.3"]\n'
        "RUN <<EOF\nset -e\nnpm install -g typescript\nEOF\n"
    )
    found = scan(text)
    assert [(f.ref, f.status) for f in found] == [
        ("ruff", "unpinned"),
        ("pytest==8.3.3", "pinned"),
        ("typescript", "unpinned"),
    ]


def test_comments_and_blank_lines_inside_an_instruction():
    parsed = instructions("# a\nRUN a \\\n  # note\n  && b\n\nFROM x\n")
    assert [(n, k) for n, k, _ in parsed] == [(2, "RUN"), (6, "FROM")]
    assert "a" in parsed[0][2] and "b" in parsed[0][2]


def test_add_checksum_must_be_a_sha_and_a_git_ref_must_be_a_commit():
    assert scan("FROM scratch\nADD --checksum=md5:abc https://example.com/t /t\n")[0].status == "unpinned"
    assert scan("FROM scratch\nADD --checksum=sha512:abc https://example.com/t /t\n")[0].status == "pinned"
    assert scan("FROM scratch\nADD https://example.com/r.git#main /r\n")[0].status == "unpinned"
    assert scan(f"FROM scratch\nADD https://example.com/r.git#{'c' * 40} /r\n")[0].status == "pinned"
