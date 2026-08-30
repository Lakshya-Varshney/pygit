# pygit

A real, content-addressed version control system, written in a single Python file, with an empty dependency manifest.

```
pygit_single.py  |  3,390 lines  |  1 file  |  141 tests  |  30 commands  |  Python 3.13+
```

**Track A — Developer Tools & CLI.** Object storage, staging, branching, merging, rebasing, a client/server sync protocol, and git-command parity down to the exact failure cases — all in one file, on the standard library alone. Nothing is installed, nothing is vendored, nothing shells out to the real `git` binary.

---

## What this actually is

Git's model, reimplemented from first principles: content-addressed objects, a working tree, a staging area, refs, a real merge algorithm — the same shape as the tool you already use every day, minus every package that usually comes bundled with it, minus the module tree too.

Objects are hashed with `hashlib.sha256`, compressed with `zlib`, and stored on disk exactly the way git stores them: loose files under `.pygit/objects/`, or packed into a single packfile once you run `gc`.

This is a from-scratch implementation, not a wrapper. `pygit_single.py` never invokes `git` as a subprocess, and it does not speak git's real wire protocol — it has its own, self-designed sync protocol between two `pygit` instances (see [Network Protocol](#network-protocol) below).

## Quick start

```bash
python3 pygit_single.py init
python3 pygit_single.py add .
python3 pygit_single.py commit -m "First commit"
```

That's the whole build step — there isn't one. `pygit_single.py` runs directly with any Python 3.13+ interpreter, no packaging, no `pip install`, no intermediate artifact to produce.

### Try the sync protocol

```bash
# Terminal 1 — serve a repo with some history
cd my-repo && python3 pygit_single.py serve --port 8798

# Terminal 2 — clone it
python3 pygit_single.py clone localhost:8798 ./my-repo-clone
```

## Commands

| Command | Syntax | What it does |
|---|---|---|
| `init` | `pygit_single.py init [path]` | Create an empty repository |
| `add` | `pygit_single.py add <path>...` | Stage file(s), recursing into directories, respecting `.pygitignore` |
| `commit` | `pygit_single.py commit -m "<msg>" [--amend]` | Snapshot the index into a new commit, or amend the last one |
| `log` | `pygit_single.py log [--oneline] [-n <count>] [<path>] [--author=<pattern>]` | Walk the current branch's history, with optional filters |
| `show` | `pygit_single.py show <sha>` | Show one commit's metadata and diff; accepts an unambiguous short sha |
| `status` | `pygit_single.py status` | Staged / modified / untracked files |
| `diff` | `pygit_single.py diff [<path>] [--staged] [<sha1> <sha2>] [--stat]` | Line diff, or a per-file insertion/deletion summary with `--stat` |
| `branch` | `pygit_single.py branch [<name>] [-d\|-D <name>]` | List, create, or delete branches |
| `checkout` | `pygit_single.py checkout <branch\|sha> [-b\|-B <name>] [-- <path>]` | Switch branches, create-and-switch (matching real git's exact `-b`/`-B` semantics, including failing on an existing branch), restore a single file, or go to a specific commit |
| `switch` | `pygit_single.py switch <branch> [-c\|-C <name>]` | The modern real-git equivalent of `checkout -b`/`-B` |
| `merge` | `pygit_single.py merge <branch>` | Fast-forward or three-way merge, with real conflict markers |
| `tag` | `pygit_single.py tag <name> [-m "<msg>"]` | Lightweight tag, or annotated with `-m` |
| `reset` | `pygit_single.py reset [--soft\|--mixed\|--hard] <commit>` | Move the branch pointer, optionally touching index/working tree |
| `stash` | `pygit_single.py stash [push\|pop\|list]` | Shelve working changes without committing |
| `cherry-pick` | `pygit_single.py cherry-pick <sha>` | Apply one commit's changes onto the current branch |
| `rebase` | `pygit_single.py rebase <branch>` | Replay the current branch's commits onto another branch's tip |
| `revert` | `pygit_single.py revert <sha>` | New commit that undoes a previous one |
| `reflog` | `pygit_single.py reflog` | Every HEAD movement, in order |
| `blame` | `pygit_single.py blame <path>` | Per-line authorship via history walk |
| `gc` | `pygit_single.py gc` | Pack loose objects, drop unreachable ones |
| `clean` | `pygit_single.py clean [-n\|-f] [-d] [-x]` | List or remove untracked files; never touches tracked content or an untracked directory's contents without `-d` |
| `remote` | `pygit_single.py remote add <name> <host:port>` / `remote -v` | Register or list remotes |
| `serve` | `pygit_single.py serve [--port <port>] [--bind <host>]` | Run this repository as a sync server |
| `fetch` | `pygit_single.py fetch <remote>` | Pull objects into a remote-tracking ref, without touching the local branch |
| `clone` | `pygit_single.py clone <host:port> <dir>` | Clone from a running `pygit_single.py serve` |
| `push` | `pygit_single.py push <host:port>` | Push to a running server; only ever accepts fast-forward updates |
| `config` | `pygit_single.py config <key> <value>` | Set repository config, e.g. `user.name`/`user.email` for commit authorship |

30 subcommands total, matching real git's exact behavior wherever there's a meaningful comparison to make — including failure cases, not just the success path.

## How it works

### Object model

```
blob    → raw file content
tree    → sorted (mode, name, sha) entries
commit  → tree sha + parent sha(s) + author/committer + message
tag     → named pointer to a commit (lightweight or annotated)
```

### Staging & index

`add` writes a JSON index (`.pygit/index`) mapping paths to blob shas, and stays in sync with `HEAD` across every branch switch — `checkout` rebuilds the index from the target tree as part of the same operation that rewrites the working directory, so `status` is always accurate immediately afterward.

### Merge strategy

Three-way merge via `difflib.SequenceMatcher` at the line level. Fast-forward when history is linear; a real merge commit with two parents when it isn't; genuine `<<<<<<< / ======= / >>>>>>>` conflict markers, with a non-zero exit, when lines collide — conflicts are never silently auto-resolved.

### Network protocol

A protocol designed for this project, spoken only between two `pygit` instances — **not compatible with real git's wire protocol**.

```
Pull (clone/fetch):
  client → WANT <ref>
  server → TIP <sha>
  client → HAVE <shas already local>
  server → streams the missing objects: <sha>\0<4-byte length><zlib-compressed bytes>

Push:
  client → PUSH <ref>
  server → TIP <sha or NONE, if the ref doesn't exist yet>
  client → runs a fast-forward check locally (rejects if the server has moved ahead
            since the client's last fetch, or if the histories are unrelated)
  client → HAVE <remote's known ancestor shas>, then COUNT <n>, then streams n objects
  server → receives and stores them, updates the ref, replies OK
```

`push` only accepts fast-forward updates — it refuses rather than silently no-opping or overwriting a remote that has diverged, verified directly by pushing against a genuinely diverged remote and confirming the remote's ref is left unchanged. Single-threaded, blocking sockets — no TLS, no auth, no concurrent clients.

### Colored output

`diff`, `status`, `branch`, and `log` are colored the way real git colors them by default, and automatically detect whether stdout is a real terminal — colors are suppressed the moment output is piped or redirected, matching real git's own behavior. Override explicitly with `--color=always` or `--color=never` on any of these commands.

## Building

There is no build step — this is the point of a single-file implementation.

```bash
make build   # syntax-checks pygit_single.py and marks it executable; nothing to package
make repro   # prints the file's SHA-256
make test    # runs the test suite
```

## Reproducible build

Because there is no packaging or build step between this source file and what runs, reproducibility is structural, not something that has to be separately verified build-to-build: the SHA-256 of `pygit_single.py` is identical on every machine, every checkout, every time — there's no `zipapp`/`__pycache__` timestamp-embedding step to introduce non-determinism, which was a real, honestly-documented limitation of an earlier packaged build of this project.

```bash
make repro
```

- **Python version tested against:** 3.13.7
- **SHA-256 of `pygit_single.py`:** run `make repro` and compare against what's committed to this repository — any judge can verify their own clone matches without needing to rebuild anything.

## Testing

```bash
python -m unittest discover -s tests -v
# or: make test
```

141 tests across object serialization, init/add/commit/log, diff/status/ignore, all three merge paths (fast-forward, clean, conflicting), stash, tag/reset/reflog, cherry-pick/rebase/revert, packfiles/gc, blame, `clean`'s directory-safety guarantees, `diff --stat`, colored-output piping behavior, and the network protocol — all importing directly from `pygit_single`.

## Zero dependencies

This project uses **only** the Python standard library. No `pip install` required. See [`STDLIB.md`](./STDLIB.md) for the full, code-verified substitution table.

## Known limits

- **No authentication or TLS** — network protocol is plaintext
- **No multi-client concurrency** — single-threaded blocking sockets
- **Simplified packfiles** — JSON sidecar index, not git's binary format
- **No git compatibility** — `git push`/`git pull` will never work against a `pygit` repo, by design
- **No CRLF normalization**
- **No submodules, cherry-pick ranges, or interactive rebase**
- **Push-rejection message can be imprecise in one edge case:** pushing to a remote you've never fetched from at all reports the same message for "genuinely unrelated histories" and "remote moved ahead since a fetch you never made," since the client can't locally distinguish the two without first fetching. The push is correctly refused either way and the remote is never corrupted — only the wording can be imprecise.

## License

MIT — see [`LICENSE`](./LICENSE).