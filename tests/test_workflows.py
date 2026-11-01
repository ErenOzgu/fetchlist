from fetchlist.workflows import scan_compose, scan_workflow

SHA = "f" * 40
HASH = "a" * 64


def scan(text):
    return scan_workflow(text, "ci.yml")


def test_uses_pinned_tag_branch_and_none():
    text = f"""
jobs:
  a:
    steps:
      - uses: actions/checkout@{SHA} # v4
      - uses: actions/setup-python@v5
      - uses: o/r@main
      - uses: o/r/sub/path@v1.2.3
      - uses: o/r
"""
    found = scan(text)
    assert [(f.ref, f.status) for f in found] == [
        (f"actions/checkout@{SHA}", "pinned"),
        ("actions/setup-python@v5", "unpinned"),
        ("o/r@main", "unpinned"),
        ("o/r/sub/path@v1.2.3", "unpinned"),
        ("o/r", "unpinned"),
    ]
    assert "tag" in found[1].why and "branch" in found[2].why and "no @ref" in found[4].why
    assert found[1].line == 6


def test_local_actions_and_expressions():
    text = "steps:\n  - uses: ./.github/actions/x\n  - uses: ${{ matrix.action }}\n"
    found = scan(text)
    assert [(f.ref, f.status) for f in found] == [("${{ matrix.action }}", "unresolved")]


def test_a_docker_action_is_an_image():
    found = scan(f"steps:\n  - uses: docker://alpine:3.20\n  - uses: docker://alpine@sha256:{HASH}\n")
    assert [(f.kind, f.status) for f in found] == [("image", "unpinned"), ("image", "pinned")]


def test_reusable_workflow():
    found = scan("jobs:\n  call:\n    uses: o/r/.github/workflows/x.yml@v1\n")
    assert found[0].status == "unpinned" and found[0].ref.endswith("x.yml@v1")


def test_run_blocks_are_scanned_with_their_line_numbers():
    text = "steps:\n  - name: x\n    run: |\n      echo hi\n      pip install ruff\n  - run: npm i -g typescript@5.6.2\n"
    found = scan(text)
    assert [(f.ref, f.status, f.line) for f in found] == [
        ("ruff", "unpinned", 5),
        ("typescript@5.6.2", "pinned", 6),
    ]


def test_a_checksum_in_another_step_does_not_verify_a_download():
    text = f"""
steps:
  - run: curl -fsSLo t https://example.com/t
  - run: echo "{HASH}  t" | sha256sum -c -
"""
    assert scan(text)[0].status == "unpinned"


def test_container_and_services_images():
    text = f"""
jobs:
  a:
    container: node:22
    services:
      db:
        image: postgres:16
      cache:
        image: redis@sha256:{HASH}
    steps:
      - uses: some/action@{SHA}
        with:
          image: not-an-image-to-pull
"""
    found = scan(text)
    assert [(f.ref, f.status) for f in found if f.kind == "image"] == [
        ("node:22", "unpinned"),
        ("postgres:16", "unpinned"),
        (f"redis@sha256:{HASH}", "pinned"),
    ]
    assert not any(f.ref == "not-an-image-to-pull" for f in found)


def test_container_with_a_mapping_has_its_image_read():
    text = "jobs:\n  a:\n    container:\n      image: ghcr.io/o/i:1\n      options: --user 1\n"
    assert scan(text)[0].ref == "ghcr.io/o/i:1"


def test_env_variables_of_the_workflow_resolve_images():
    text = f"""
env:
  IMG: ghcr.io/o/i@sha256:{HASH} # pinned on 2026-11-01
jobs:
  a:
    steps:
      - run: docker pull "${{IMG}}"
      - run: docker pull "$OTHER"
"""
    found = scan(text)
    assert [(f.status, f.ref) for f in found] == [
        ("pinned", f"ghcr.io/o/i@sha256:{HASH}"),
        ("unresolved", "$OTHER"),
    ]


def test_composite_action_steps():
    text = "runs:\n  using: composite\n  steps:\n    - run: pip install ruff\n      shell: bash\n"
    assert scan(text)[0].ref == "ruff"


def test_a_command_in_a_comment_is_not_a_fetch():
    assert scan("steps:\n  - run: |\n      # pip install ruff\n      echo ok\n") == []


def test_compose_images():
    text = f"services:\n  web:\n    image: nginx:1.27\n  db:\n    image: 'postgres@sha256:{HASH}'\n"
    found = scan_compose(text, "compose.yml")
    assert [(f.ref, f.status) for f in found] == [
        ("nginx:1.27", "unpinned"),
        (f"postgres@sha256:{HASH}", "pinned"),
    ]


def compose_refs(text: str) -> list[str]:
    return [f.ref for f in scan_compose(text, "compose.yml")]


def test_a_compose_image_that_is_built_here_is_not_a_download():
    assert compose_refs("services:\n  web:\n    image: app:local\n    build: .\n") == []
    assert compose_refs("services:\n  web:\n    build: .\n    image: app:local\n") == []
    long = "services:\n  web:\n    build:\n      context: .\n      args:\n        a: b\n\n    # name\n    image: app:local\n"
    assert compose_refs(long) == []
    assert (
        compose_refs("services:\n  web:\n    build: .\n# a comment at column 0\n    image: app:local\n") == []
    )


def test_a_build_in_another_service_does_not_excuse_an_image():
    text = "services:\n  web:\n    build: .\n    image: app:local\n  db:\n    image: postgres:16\n  cache:\n    image: redis:7\n"
    assert compose_refs(text) == ["postgres:16", "redis:7"]
    text = "services:\n  db:\n    image: postgres:16\n  web:\n    build: .\n"
    assert compose_refs(text) == ["postgres:16"]


def test_a_nested_build_key_is_not_the_services_build():
    text = "services:\n  web:\n    image: app:1\n    labels:\n      build: yes\n"
    assert compose_refs(text) == ["app:1"]


def test_a_ref_must_be_a_full_commit_to_count():
    assert scan("steps:\n  - uses: o/r@abcdef1234\n  - uses: o/r@release-1.2\n")[0].status == "unpinned"
    assert scan("steps:\n  - uses: o/r@release-1.2\n")[0].status == "unpinned"
    assert scan(f"steps:\n  - uses: o/r@{SHA[:39]}\n")[0].status == "unpinned"
