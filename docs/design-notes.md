# Design notes

Why fetchlist is built the way it is. The README says what it does; this says what was decided, what else was
considered and how it was checked. The decisions are in the order a reader usually asks about them.

## The problem in one paragraph

Most of what a build downloads is named in files that are already in the repository: the `FROM` line, the `uses:` of
a workflow, a `curl` in a script, a line in `requirements.txt`. Whether each of those is fixed or can change underneath
you is visible in the same line (a digest, a commit, an exact version, or a tag, a branch, a range). Nobody reads them
all, so the answer to "what does this build trust?" lives in nobody's head. The tool reads them all, prints the answer,
and fails when the answer is "more than you meant to".

## Decisions

### List first, judge second

`scan` is the product and `check` is a filter on it. Every download becomes one record: where it is (file and line),
what it is (image, action, url, package, git, include), what it is exactly (`ref`), whether it is fixed (`status`), why,
and which host serves it. `check` fails on some statuses, `mirror` groups the records by host, and the JSON output is
the records. A tool that only said "3 problems" could not be argued with; a list can be read, diffed in a pull request
and fed to something else.

### Four statuses, not two

"Pinned or not" is too coarse for downloads by URL, which is where real files differ:

| Status | Why it exists |
|---|---|
| `pinned` | the content is fixed by something in the repository |
| `unpinned` | it is not |
| `verified` | a checksum check is in the same step, but the expected value may come from the server that is being checked |
| `unresolved` | the reference holds a variable this file does not define, so the answer is unknown |

`verified` is the honest middle. `curl -O https://host/tool && curl -O https://host/sums && sha256sum -c sums` is a good
habit and protects against a corrupted download, but a server that serves a bad tool serves a matching bad checksum
file. The status says that and the default `check` accepts it; `--strict` does not. `unresolved` exists so that the
tool never guesses: `docker run "$IMAGE"` with no definition of `IMAGE` in the file is neither pinned nor unpinned, and
saying either would be a claim the tool cannot back up.

Not used: a score or a severity. The question has a definite answer per line, and ranking "tag" against "branch" would
be opinion.

### No YAML library, no dependencies

CI files are read by line: a key, its value, the keys that enclose it by indentation, and block scalars for `run: |`.
That is enough for `uses:`, `image:`, `run:`, `script:` and `include:` as they are written in practice. It is not a YAML
parser, and the README lists what it does not understand (flow mappings, anchors, multi-document files).

Why accept that: the tool is meant to run in CI on code it did not write, so what it imports is part of what the
pipeline trusts, and a tool whose point is "know what you download" should not download anything. It has no
dependencies at all. The cost is real, and it is paid in the direction that is safe: when a line cannot be understood,
the result is `unresolved` or nothing at all, never a `pinned` it did not earn.

### The unit of "checked" is the step

Whether a checksum check counts for a download depends on how far apart they may be. Anywhere in the file would make one
`sha256sum` bless every download in a 400-line workflow. So the unit is the smallest thing that runs as one: one
`run:` block, one `RUN` instruction, one GitLab `script` entry, one blank-line-separated paragraph of a shell script or
Makefile. The cost is that a check one paragraph later is not seen. That is a cheap thing to fix in the script (put them
together), which is the behaviour the rule is meant to cause.

### `curl | sh` is its own rule

A pipe into a shell (`| sh`, `| sudo bash`, `sh -c "$(curl ...)"`, `bash <(curl ...)`, and the same into `python`,
`perl`, `ruby`) is `unpinned` even when a checksum command is in the same step, because the check cannot be between the
download and the execution. The same goes for plain `http://` and `curl -k`, unless a literal hash is checked: a literal
sha256 fixes the content whatever the transport.

### Variables the file defines are filled in

Real files keep digests and URLs in `env:`, `ARG`, `export` and Makefile variables. Without substitution the tool would
report `unresolved` on exactly the files that did the right thing (a workflow that pins `IMG` once and uses it in five
steps). So it fills in `${NAME}`, `$NAME`, `$(NAME)`, `${NAME:-default}` and `${{ env.NAME }}` from definitions in the same
file. A name defined twice with different values is not substituted, because the file does not say which applies.
Variables defined in another file (a workflow `env:` used by a script it calls) stay `unresolved`; that is true to what
the file says.

### Allowances need a reason, and go stale loudly

Some unpinned things are right: a throw-away container in a smoke test, an old image used on purpose to see a scanner
fail. The choices were a comment in the file (invisible to the tool), a `# fetchlist: ignore` marker (the exception
and the reason drift apart), or a configuration file. It is the file, with three rules: a reason is required, an
allowance matches one file glob and one exact `ref`, and an allowance that matches nothing makes `check` fail. The last
rule is the one that matters: an exception list only ever grows unless something removes entries, and a pin that is
fixed later should take its excuse with it.

### A file it cannot read is exit 2, not a pass

A `pom.xml` with a `DOCTYPE` or `ENTITY`, a file over 2 MB, a file that cannot be opened: the tool reports it on stderr
and `check` exits 2. A scanner that skips what it cannot read and exits 0 teaches people that green means clean. XML
entities are not expanded at all (the standard library parser would expand them; that is the classic way to make a
scanner of other people's files eat memory), so a pom that uses them is refused.

### Local things are not downloads

A smoke test that curls `127.0.0.1`, `pip install .`, `go install ./...`, a local action `./.github/actions/x`, and an
image the same file built with `docker build -t` are not things anyone downloads, and reporting them would drown the real
findings. Found by running the tool on real repositories: the first version listed every health check.

### `mirror` is the same list, grouped by host

A build that has to run from an internal mirror, or in a network that allows a few hosts, has a list of things to
make available. The list already exists in the build files; `mirror` writes it down as hosts, images, actions, packages
or URLs. It does not know what a registry redirects to (layers come from other hosts) and says so.

## How it was checked

- **Tests per rule.** Each pinning rule has a test for the case that is pinned and the case that is not, because the
  mistake worth catching is the one in the middle (`@abcdef1234` is not a commit, `typescript@5` is not a version).
- **Mutated inputs.** The sample files are mutated 300 times each (a line dropped, duplicated, cut, swapped, junk
  inserted) and every scanner must either return findings that point at a line that exists, or refuse the file by name.
- **A mutation check, once and by hand.** 112 single-line changes to the code that decides a status, a pattern or an
  exit code; after each one the suite had to fail. 31 survived the first run. Most pointed at a missing test, which was
  added (a short digest, `localhost:5000/img` without a tag, an allowance for something already pinned, the GitHub
  annotation levels); some pointed at code that did nothing (a check for a leading dash that the next line made
  redundant), which was removed. The final run killed all of them. It is not in CI, the list is not exhaustive, and it
  says what was checked once, not what is guaranteed.
- **The tool checks itself.** CI runs `fetchlist check . --strict` on this repository. That found a bug before release:
  `fetchlist/dockerfile.py` was being read as a Dockerfile because its name starts with `dockerfile.`.
- **Real repositories.** The first version was run on the author's own repositories. The false positives it showed
  (loopback health checks, images built in the same file, a Maven BOM, `${VAR:?message}`) became tests; the true
  positives are described in the README.

## What would be changed next

In [ROADMAP.md](../ROADMAP.md), roughly in this order:

1. `pyproject.toml`, `package.json` and lock files. Python and Node projects declare most of their dependencies there,
   and today only `requirements.txt` and shell commands are read.
2. `apt-get`, `apk` and `yum` installs: the unpinned ones are easy to see, and `mirror` should list the distribution hosts.
3. `fetchlist pin`, which proposes the digest or commit for a reference (it needs the network, and so a different trust
   story from the rest of the tool, which does not use it).
4. A SARIF output, so the findings show up in the code-scanning view of GitHub.
5. Helm charts, Terraform providers and modules, and `.pre-commit-config.yaml`.

## Questions this design usually draws

**Why not a YAML parser?** The point of the tool is to know what a build trusts, and a dependency is something the
build trusts. It reads CI files the way people write them, says `unresolved` where it cannot tell, and has a test
suite that mutates real-looking files to check it never crashes on the ones that are not.

**Why does `verified` not fail?** Because it is better than nothing and the tool cannot tell how good. If you want the
stricter reading, `--strict` is one flag. A literal hash in the step (or in a variable the file defines) is `pinned`.

**How is this different from Dependabot, Renovate or Scorecard?** Those update pins or score a repository. This lists what
is not pinned in the files you point it at, across Dockerfiles, CI and scripts at once, and produces the list a mirror
needs. It works well next to them: `check` fails the build, Dependabot proposes the fix.

**Does it know a digest is right?** No. It does not use the network, so it does not know that a digest exists or that a
tag still points where it did. It knows that a reference is fixed, not that it is good.

**What if my CI is generated?** Run it on the generated files. It reads files, not templates.

**What does it miss?** Anything installed by a package manager it does not know (`apt`, `brew`, `cargo`, `gem`), anything
fetched by code inside the application at run time, and dependencies declared only in `pyproject.toml` or `package.json`.

## Three-minute demo

```sh
pip install git+https://github.com/ErenOzgu/fetchlist
git clone https://github.com/ErenOzgu/fetchlist && cd fetchlist
fetchlist check examples/sample; echo "exit $?"      # 18 not pinned, exit 1
fetchlist scan examples/sample | head -20            # the full list, with the reason for each
fetchlist mirror examples/sample --what hosts        # what the build has to reach
fetchlist check . --strict                           # this repository is clean
```

Then open `.fetchlist.toml` in the sample: one allowance with its reason. Delete the line it excuses from the sample
workflow and run `check` again: it fails, and says the allowance matches nothing.
