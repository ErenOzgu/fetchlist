from fetchlist.gitlab import scan_gitlab

SHA = "9" * 40


def scan(text):
    return scan_gitlab(text, ".gitlab-ci.yml")


def refs(text):
    return [(f.kind, f.ref, f.status) for f in scan(text)]


def test_image_forms():
    text = """
image: maven:3.9
build:
  image:
    name: gcr.io/kaniko-project/executor:v1.23.2
    entrypoint: [""]
  script: [echo]
test:
  image: alpine@sha256:%s
""" % ("a" * 64)
    assert refs(text) == [
        ("image", "maven:3.9", "unpinned"),
        ("image", "gcr.io/kaniko-project/executor:v1.23.2", "unpinned"),
        ("image", "alpine@sha256:" + "a" * 64, "pinned"),
    ]


def test_services_in_both_forms():
    text = """
job:
  services:
    - postgres:16
    - name: docker:28-dind
      alias: docker
  script: [echo]
"""
    assert refs(text) == [("image", "postgres:16", "unpinned"), ("image", "docker:28-dind", "unpinned")]


def test_scripts_are_scanned_as_shell_in_all_three_places():
    text = """
job:
  before_script:
    - pip install ruff
  script:
    - npm i -g typescript@5.6.2
    - |
      curl -fsSLO https://example.com/t
      sha256sum -c sums
  after_script:
    - go install example.com/x@latest
"""
    got = [(f.ref, f.status) for f in scan(text)]
    assert got == [
        ("ruff", "unpinned"),
        ("typescript@5.6.2", "pinned"),
        ("https://example.com/t", "verified"),
        ("example.com/x@latest", "unpinned"),
    ]


def test_script_items_at_the_indent_of_the_key():
    text = "job:\n  script:\n  - pip install ruff\n  other: x\n"
    assert [f.ref for f in scan(text)] == ["ruff"]


def test_includes():
    text = f"""
include:
  - remote: https://example.com/ci.yml
  - remote: https://raw.githubusercontent.com/o/r/{SHA}/ci.yml
  - project: group/shared
    ref: main
    file: /ci.yml
  - project: group/shared
    ref: {SHA}
    file: /ci.yml
  - template: Security/SAST.gitlab-ci.yml
  - component: gitlab.com/group/comp@1.0.0
  - component: gitlab.com/group/comp@{SHA}
  - local: /ci/local.yml
stages: [a]
"""
    got = [(f.ref, f.status) for f in scan(text)]
    assert got == [
        ("https://example.com/ci.yml", "unpinned"),
        (f"https://raw.githubusercontent.com/o/r/{SHA}/ci.yml", "pinned"),
        ("group/shared@main", "unpinned"),
        (f"group/shared@{SHA}", "pinned"),
        ("template:Security/SAST.gitlab-ci.yml", "unpinned"),
        ("gitlab.com/group/comp@1.0.0", "unpinned"),
        (f"gitlab.com/group/comp@{SHA}", "pinned"),
    ]


def test_inline_include():
    assert refs("include: 'https://example.com/ci.yml'\n") == [
        ("include", "https://example.com/ci.yml", "unpinned")
    ]
    assert refs("include: '/local.yml'\n") == []


def test_image_from_a_variable_the_file_defines():
    text = "variables:\n  BASE: alpine:3.20\njob:\n  image: $BASE\n"
    assert refs(text) == [("image", "alpine:3.20", "unpinned")]
