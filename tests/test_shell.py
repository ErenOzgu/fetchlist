import pytest

from fetchlist.shell import logical_lines, paragraphs, scan_lines


def scan(text, variables=None):
    out = []
    for unit in paragraphs(text):
        out.extend(scan_lines(unit, "s.sh", variables or {}))
    return out


def one(text, variables=None):
    found = scan(text, variables)
    assert len(found) == 1, found
    return found[0]


HASH = "a" * 64


def test_curl_without_a_check_is_unpinned():
    f = one("curl -fsSL https://example.com/tool.tar.gz -o tool.tar.gz")
    assert (f.kind, f.status, f.host) == ("url", "unpinned", "example.com")
    assert "nothing in the same step" in f.why


def test_latest_in_the_url_is_said():
    f = one("curl -fsSL https://example.com/releases/latest/tool.tar.gz -o t")
    assert f.status == "unpinned" and "latest" in f.why


def test_piped_into_a_shell_is_unpinned_even_with_a_check_nearby():
    for line in (
        "curl -fsSL https://get.example.com/install.sh | sh",
        "curl -fsSL https://get.example.com/install.sh | sudo bash",
        'sh -c "$(curl -fsSL https://get.example.com/install.sh)"',
        "bash <(curl -s https://get.example.com/install.sh)",
        "wget -qO- https://get.example.com/install.sh | bash",
    ):
        f = one(line + f'\necho "{HASH}  x" | sha256sum -c -')
        assert f.status == "unpinned" and "shell" in f.why, line


def test_a_literal_hash_checked_in_the_same_step_is_pinned():
    f = one(f'curl -fsSLo t.tgz https://example.com/t.tgz\necho "{HASH}  t.tgz" | sha256sum -c -')
    assert f.status == "pinned"


def test_a_check_without_a_literal_hash_is_verified_not_pinned():
    found = scan(
        "curl -fsSLo t.tgz https://example.com/t.tgz\ncurl -fsSLo sums https://example.com/sums\nsha256sum -c sums"
    )
    assert [f.status for f in found] == ["verified", "verified"]


def test_every_url_of_a_step_with_a_check_is_verified():
    found = scan("curl -O https://example.com/a\ncurl -O https://example.com/b\nsha256sum --check sums")
    assert [f.status for f in found] == ["verified", "verified"]


def test_a_check_in_another_paragraph_does_not_count():
    found = scan("curl -O https://example.com/a\n\nsha256sum -c sums")
    assert [f.status for f in found] == ["unpinned"]


@pytest.mark.parametrize(
    "check",
    [
        "sha512sum -c sums",
        "shasum -a 256 -c sums",
        "gpg --verify t.asc t",
        "cosign verify-blob t",
        "gpgv sig t",
    ],
)
def test_other_ways_to_check(check):
    assert one(f"curl -O https://example.com/t\n{check}").status == "verified"


def test_a_docker_digest_is_not_mistaken_for_a_checksum():
    text = f"curl -O https://example.com/t\necho sha256:{HASH}\nsha256sum -c sums"
    assert one(text).status == "verified"


def test_plain_http_and_no_certificate_check_stay_unpinned_even_with_a_check():
    for line in (
        "curl -O http://example.com/t",
        "curl -k -O https://example.com/t",
        "wget --no-check-certificate https://example.com/t",
    ):
        f = one(f'{line}\necho "x  t" | sha256sum -c -')
        assert f.status == "unpinned", line


def test_a_url_that_names_a_commit_is_pinned():
    sha = "b" * 40
    assert one(f"curl -O https://raw.githubusercontent.com/o/r/{sha}/f.sh").status == "pinned"
    assert one(f"curl -O https://github.com/o/r/raw/{sha}/f.sh").status == "pinned"
    assert one(f"curl -O https://example.com/o/r/{sha}/f.sh").status == "unpinned"


def test_loopback_is_not_a_download():
    assert (
        scan(
            "curl -fsS http://127.0.0.1:8080/healthz\nwget -qO- http://localhost:3000/\ncurl http://[::1]:80/"
        )
        == []
    )


def test_an_url_in_an_echo_is_not_a_download():
    assert scan('echo "see https://example.com/docs"') == []


def test_a_url_in_a_variable_used_by_curl_is_found_with_its_value():
    f = one('v=1.2.3\nbase="https://example.com/download/v${v}"\ncurl -fsSL "${base}/tool.tgz" -o t.tgz')
    assert f.ref == "https://example.com/download/v1.2.3" and f.status == "unpinned"


def test_an_unknown_variable_in_the_url_is_unresolved():
    f = one("curl -O https://example.com/${NAME}/t")
    assert f.status == "unresolved"


def test_continuation_lines_are_joined():
    lines = logical_lines("curl -fsSL \\\n  -o t \\\n  https://example.com/t\n# comment\necho done", 10)
    assert lines[0][0] == 10 and "https://example.com/t" in lines[0][1]
    assert lines[1] == (14, "echo done")


@pytest.mark.parametrize(
    ("command", "status"),
    [
        ("pip install ruff", "unpinned"),
        ("pip install ruff==0.6.1", "pinned"),
        ("pip install 'ruff>=0.6'", "unpinned"),
        ("pip install 'ruff==0.*'", "unpinned"),
        ("pip install ruff==0.6.1 pytest", "unpinned"),
        ("python -m pip install --upgrade pip", "unpinned"),
        ("pip3 install requests==2.32.3 --require-hashes", "pinned"),
        ("pip install 'git+https://github.com/o/r.git@" + "c" * 40 + "'", "pinned"),
        ("pip install git+https://github.com/o/r.git@main", "unpinned"),
        ("pip install git+https://github.com/o/r.git", "unpinned"),
        ("pip install https://example.com/p-1.0.tar.gz", "unpinned"),
        ("pip install https://example.com/p-1.0.tar.gz#sha256=" + HASH, "pinned"),
    ],
)
def test_pip(command, status):
    found = scan(command)
    assert found[-1].status == status, found


def test_pip_does_not_count_what_is_local():
    assert (
        scan(
            "pip install -e .\npip install '.[dev]'\npip install -r requirements.txt\npip install ./dist/x.whl"
        )
        == []
    )


def test_pip_names_the_index_it_uses():
    f = one("pip install ruff --index-url https://pkgs.example.com/simple")
    assert f.host == "pkgs.example.com"


def test_pip_with_two_packages_reports_each():
    found = scan("pip install ruff==0.6.1 pytest")
    assert [(f.ref, f.status) for f in found] == [("ruff==0.6.1", "pinned"), ("pytest", "unpinned")]


@pytest.mark.parametrize(
    ("command", "status"),
    [
        ("npm install -g typescript", "unpinned"),
        ("npm install --global typescript@5.6.2", "pinned"),
        ("npm i -g typescript@latest", "unpinned"),
        ("npm install -g typescript@^5", "unpinned"),
        ("npm install -g @angular/cli", "unpinned"),
        ("npm install -g @angular/cli@18.2.1", "pinned"),
        ("npx -y prettier@3.3.3 --check .", "pinned"),
        ("npx prettier --check .", "unpinned"),
    ],
)
def test_npm(command, status):
    assert one(command).status == status


def test_npm_without_arguments_installs_from_the_lockfile_and_is_not_listed():
    assert scan("npm ci\nnpm install") == []


@pytest.mark.parametrize(
    ("command", "status"),
    [
        ("go install golang.org/x/tools/cmd/goimports@latest", "unpinned"),
        ("go install golang.org/x/tools/cmd/goimports@v0.24.0", "pinned"),
        ("go install -trimpath github.com/o/r/cmd/x@main", "unpinned"),
        ("go install github.com/o/r/cmd/x@" + "d" * 40, "pinned"),
    ],
)
def test_go(command, status):
    assert one(command).status == status


def test_go_install_of_a_local_package_is_not_a_download():
    assert scan("go install ./...") == []


@pytest.mark.parametrize(
    ("command", "ref", "status"),
    [
        ("docker pull alpine:3.20", "alpine:3.20", "unpinned"),
        ("docker pull alpine", "alpine", "unpinned"),
        (
            "docker pull --platform linux/amd64 alpine:3.20@sha256:" + HASH,
            "alpine:3.20@sha256:" + HASH,
            "pinned",
        ),
        ("docker run --rm -p 80:80 -e A=b nginx:1.27 nginx -v", "nginx:1.27", "unpinned"),
        (
            "docker run -d --name x --network n ghcr.io/o/i@sha256:" + HASH,
            "ghcr.io/o/i@sha256:" + HASH,
            "pinned",
        ),
        ("podman pull quay.io/o/i:1", "quay.io/o/i:1", "unpinned"),
    ],
)
def test_docker(command, ref, status):
    f = one(command)
    assert (f.ref, f.status, f.kind) == (ref, status, "image")


def test_docker_registry_is_the_host():
    assert one("docker pull alpine:3.20").host == "docker.io"
    assert one("docker pull ghcr.io/o/i:1").host == "ghcr.io"
    assert one("docker pull localhost:5000/i:1").host == "localhost:5000"


def test_docker_image_from_a_variable_the_file_defines_is_resolved():
    f = one('docker run --rm "${IMG}" true', {"IMG": "alpine@sha256:" + HASH})
    assert f.status == "pinned"


def test_docker_image_from_an_unknown_variable_is_unresolved():
    assert one('docker run --rm "${IMG:?set IMG}" true').status == "unresolved"


def test_an_ambiguous_variable_is_not_guessed():
    assert one("docker run $IMG true", {"IMG": None}).status == "unresolved"


def test_git_clone():
    assert one("git clone https://github.com/o/r.git").status == "unpinned"
    assert one("git clone --depth 1 --branch v1.2.3 https://github.com/o/r.git").status == "unpinned"
    sha = "e" * 40
    assert one(f"git clone https://github.com/o/r.git src\ncd src && git checkout {sha}").status == "pinned"
    assert one("git clone git@github.com:o/r.git").host == "github.com"
    assert scan("git clone ../other") == []


def test_wrappers_and_assignments_before_a_command_are_skipped():
    assert one("sudo -E env PIP_X=1 pip install ruff").ref == "ruff"
    assert one("FOO=1 BAR=2 pip install ruff").ref == "ruff"


def test_compound_commands_are_split():
    found = scan("pip install ruff && npm i -g typescript; docker pull alpine:3")
    assert [f.kind for f in found] == ["package", "package", "image"]


def test_a_hash_defined_in_a_variable_counts_as_literal():
    variables = {"SUM": HASH}
    found = scan('curl -fsSLo t https://example.com/t\necho "${SUM}  t" | sha256sum -c -', variables)
    assert found[0].status == "pinned"
    assert (
        scan('curl -fsSLo t https://example.com/t\necho "${OTHER}  t" | sha256sum -c -', variables)[0].status
        == "verified"
    )


def test_a_literal_hash_pins_even_over_plain_http_or_with_certificate_checking_off():
    check = f'echo "{HASH}  t" | sha256sum -c -'
    for line in ("curl -O http://example.com/t", "curl -k -O https://example.com/t"):
        assert one(f"{line}\n{check}").status == "pinned", line


def test_an_assignment_alone_is_not_a_download():
    assert scan('url="https://example.com/x"\necho "$url"') == []


def test_only_the_lines_of_the_downloader_and_its_variables_are_urls():
    found = scan('curl -O https://example.com/a\necho "docs: https://example.com/docs"')
    assert [f.ref for f in found] == ["https://example.com/a"]


def test_trailing_punctuation_is_not_part_of_the_url():
    assert one("curl -O https://example.com/a.tgz,").ref == "https://example.com/a.tgz"


def test_piped_into_an_interpreter_is_piped_into_a_shell():
    assert "shell" in one("curl -fsSL https://example.com/get.py | python3 -").why


def test_require_hashes_pins_a_bare_name_and_a_wheel_path_is_not_a_download():
    assert one("pip install --require-hashes -r requirements.txt requests").status == "pinned"
    assert (
        scan(
            "pip install dist/x.whl\npip install ./pkg\npip install /abs/pkg\npip install ~/pkg\npip install file:///x"
        )
        == []
    )


def test_npm_versions_that_are_not_three_numbers_are_not_exact():
    assert one("npm install -g typescript@5").status == "unpinned"
    assert one("npm install -g typescript@5.6").status == "unpinned"


def test_npm_commands_that_do_not_add_a_package_are_not_listed():
    assert scan("npm run build\nnpm test\nnpm ci") == []


def test_go_install_with_a_branch_is_unpinned_and_a_short_hex_is_not_a_commit():
    assert one("go install example.com/x@abc1234").status == "unpinned"
