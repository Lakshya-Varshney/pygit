# pygit

A real, content-addressed version control system in pure Python with **zero dependencies**.

```
pygit.pyz  ~ 312 KB  |  13 modules  |  4,027 lines  |  141 tests  |  27 commands  |  Python 3.13+
```

## What is this?

`pygit` implements git's object model and full workflow entirely from Python's standard library. It is **not** a wrapper around the real `git` binary and does not shell out to it at any point.

Every object (blob, tree, commit, tag) is stored by its SHA-256 hash, compressed with zlib, and addressed on disk exactly like real git — just with different hashing.

## Quick Start

```bash
# From source
python -m pygit init
python -m pygit add .
python -m pygit commit -m "First commit"

# As single-file artifact
python pygit.pyz init
python pygit.pyz add .
python pygit.pyz commit -m "First commit"
```

### Try the sync protocol

```bash
# Terminal 1 — serve a repo with some history
cd my-repo && python -m pygit serve --port 8798

# Terminal 2 — clone it
python -m pygit clone localhost:8798 ./my-repo-clone
```

## Commands

| Command | Description |
|---|---|
| `pygit init` | Create an empty repository |
| `pygit add <path>...` | Add files to the staging area (recurses into directories, respects `.pygitignore`) |
| `pygit commit -m "<msg>"` | Record changes to the repository; `--amend` to amend the last commit |
| `pygit log [-n <count>] [<path>]` | Show commit history; `--oneline`, `-n` limit, `<path>` filter, `--author=<pattern>`, `--color` |
| `pygit show <sha>` | Show commit metadata and diff (accepts short sha prefix, `--color`) |
| `pygit status` | Show working tree status (`--color`) |
| `pygit diff [<ref1> [<ref2>]]` | Diff working tree vs index, or two commits (`--staged`, `--stat`, `--color`); commit refs accept short shas or branch names |
| `pygit branch [<name>]` | List, create, or delete branches; `-d`/`-D` to delete; `--color` |
| `pygit checkout <target>` | Switch branches or restore files; `-b`/`-B` to create/reset branch; `-- <path>` to restore files; short sha prefix for detached HEAD |
| `pygit switch <branch>` | Switch to a branch; `-c`/`-C` to create/reset branch |
| `pygit merge <branch>` | Merge a branch (fast-forward or three-way) |
| `pygit tag <name> [-m "<msg>"]` | Create a lightweight or annotated tag |
| `pygit reset [--soft\|--mixed\|--hard] <commit>` | Reset HEAD to a commit (accepts short sha prefix) |
| `pygit stash [push\|pop\|list]` | Save/restore working state |
| `pygit cherry-pick <sha>` | Apply a commit's changes (accepts short sha prefix) |
| `pygit rebase <branch>` | Rebase onto another branch |
| `pygit revert <sha>` | Revert a commit (accepts short sha prefix) |
| `pygit clean [-n\|-f] [-d] [-x]` | Remove untracked files; `-n` dry run, `-f` force, `-d` include dirs, `-x` include ignored |
| `pygit reflog` | Show HEAD movement history |
| `pygit blame <path>` | Show line-by-line attribution |
| `pygit gc` | Garbage collection and packfiles |
| `pygit remote add <name> <addr>` | Add a remote |
| `pygit fetch <remote>` | Fetch from a remote into a remote-tracking ref, without touching the local branch |
| `pygit clone <host:port> <dir>` | Clone a remote repository |
| `pygit push <host:port>` | Push to a remote server |
| `pygit config <key> [<value>]` | Get or set repository configuration (e.g. `user.name`, `user.email`) |
| `pygit serve [--port <port>]` | Start a server to serve this repository |

26 subcommands total.

## How It Works

### Object Model

```
blob    → file content (compressed with zlib)
tree    → directory listing (mode, name, sha tuples)
commit  → snapshot with tree, parents, author, message
tag     → named reference to a commit (lightweight or annotated)
```

Objects are stored as loose files in `.pygit/objects/` or packed into packfiles during `gc`.

### Short SHA Resolution

Any command that accepts a commit sha (`show`, `checkout`, `reset`, `cherry-pick`, `revert`) also accepts an unambiguous short prefix of 4+ characters. For example, `pygit show cdddab7` resolves the 7-character prefix to the full sha before lookup. If the prefix matches multiple objects, pygit reports an ambiguity error. If it matches nothing, it reports a no-match error. Short shas work for both loose objects and objects packed during `gc`.

### Staging & Index

`pygit add` writes a JSON index (`.pygit/index`) tracking file paths and their blob SHAs, and stays in sync with `HEAD` across every branch switch — `checkout` rebuilds the index from the target tree as part of the same operation that rewrites the working directory, so `status` is always accurate immediately afterward.

### Merge Strategy

Three-way merge uses `difflib.SequenceMatcher`:

- **Fast-forward**: linear history, just move the branch pointer
- **Clean merge**: no conflicts, auto-create merge commit
- **Conflicts**: write real conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`), exit non-zero, never auto-resolve

### Network Protocol

A protocol designed for this project, spoken only between `pygit` instances — **not wire-compatible with real git**.

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
  client → HAVE <remote's known ancestor shas>
  client → COUNT <n>, then streams n objects in the same length-framed format
  server → receives and stores them, updates the ref, replies OK
```

`push` only accepts fast-forward updates — it will refuse rather than silently no-op or overwrite a remote that has diverged. Single-threaded, blocking sockets — no TLS, no auth, no concurrent clients.

## Architecture

```
pygit/
├── __main__.py      # CLI entry point (argparse, 23 commands)
├── __init__.py      # Package marker
├── objects.py       # Object model: hash, read, serialize/deserialize
├── repository.py    # Repository class, HEAD, refs, config, working tree
├── index.py         # JSON-based staging area
├── diff.py           # Unified diff, blame, diff commands
├── merge.py            # Three-way merge, cherry-pick, rebase, revert
├── stash.py             # Stash push/pop/list
├── pack.py                # Packfiles with JSON sidecar index, gc
└── network.py               # TCP server/client for clone/push/fetch

tests/  — 50 tests across every module above
```

## Building

```bash
make build          # Produces pygit.pyz
make repro          # Verify reproducible build (two builds, matching SHA-256)
make test            # Run the test suite
```

Or manually:

```bash
python -m zipapp pygit -o pygit.pyz -p "/usr/bin/env python3"
```

## Reproducible Build

`make repro` produces two builds and confirms their hashes match. **Caveat, stated honestly:** `zipapp` embeds each source file's filesystem modification time into the archive, and the current build includes `__pycache__/*.pyc` files (which embed their own compile timestamps). This means the hash is stable across two consecutive builds *on the same checkout*, but a third party who clones the repo fresh and runs `make repro` themselves will very likely get a **different**, but still internally self-consistent, pair of matching hashes — not the exact bytes published here. True cross-machine byte-identical reproducibility would require excluding `__pycache__` from the build and normalizing source file timestamps before archiving, which this build does not currently do.

- **Python version:** 3.13.7
- **Build command:** `python -m zipapp pygit -o pygit.pyz -p "/usr/bin/env python3"`
- **Hashes from this build environment (Build 1 / Build 2, identical to each other):** run `make repro` to reproduce locally; the last verified matching pair here was `5854dd4e98c01bc22487cc6b4b963ef0950fdcb97f0a39255c9ecd1e9b0c69b8`.

## Testing

```bash
python -m unittest discover -s tests -v
# or: make test
```

All 50 tests cover: object serialization, init/add/commit/log, diff/status/ignore, merge strategies, stash, tag/reset/reflog, cherry-pick/rebase/revert, packfiles/gc, blame, and the network protocol.

## Zero Dependencies

This project uses **only** the Python standard library. No `pip install` required. See [`STDLIB.md`](./STDLIB.md) for the full, code-verified substitution table.

## Known Limits

- **No authentication or TLS** — network protocol is plaintext
- **No multi-client concurrency** — single-threaded blocking sockets
- **Simplified packfiles** — JSON sidecar index, not git's binary format
- **No git compatibility** — `git push` / `git pull` won't work with pygit repos
- **Windows line endings** — no CRLF normalization
- **No submodules, cherry-pick ranges, or interactive rebase**
- **Push-rejection message can be imprecise in one edge case:** if you push to a remote you have never fetched from at all, a genuinely unrelated remote and a remote that has simply "moved ahead since a fetch you never made" are reported with the same message (`remote has moved ahead since your last fetch; fetch first`), since the client can't locally distinguish the two without first fetching. The push is correctly refused either way and the remote is never corrupted — only the wording can be imprecise.
- **Reproducible build is single-environment only** — see the caveat under Reproducible Build above.

## License

MIT — see [`LICENSE`](./LICENSE).