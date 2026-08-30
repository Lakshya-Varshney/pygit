# STDLIB.md — Python Standard Library Substitutions

This project uses **zero external dependencies**. Every feature is implemented with Python's standard library. Every row below is backed by an actual import/usage in the codebase — verified against the real code, not just claimed.

| Would normally use | Used instead | Why |
|---|---|---|
| `GitPython` / `dulwich` / `pygit2` | This entire project | The point of the build |
| `diff-match-patch` and similar diff libs | `difflib.SequenceMatcher` / `unified_diff` (stdlib) | Line-level diffing, no C extension needed |
| `zstandard` / `python-lz4` | `zlib` (stdlib) | Object and packfile compression, matches what real git itself uses |
| `pyyaml` for config/state | `json` (stdlib) | Index, stash, and pack sidecar storage |
| `configobj` / custom INI parsers | `configparser` (stdlib) | Repository config file |
| `click` / `typer` (CLI framework) | `argparse` (stdlib) | 23 subcommands via `subparsers`, no framework needed |
| `requests` / `paramiko` (networking) | `socket` (stdlib) | Hand-rolled `WANT`/`PUSH`/`TIP`/`HAVE`/`COUNT` sync protocol, plus binary length-framed object transfer |
| `pathspec` (gitignore-style matching) | `fnmatch` (stdlib) | Glob matching for `.pygitignore` |
| `pytest` | `unittest` (stdlib) | Zero-dep test framework requirement, 50 tests |
| `shortuuid` / third-party `uuid` packages | `uuid` (stdlib) | Generated identifiers |
| A crawler/indexing library for `blame` | Manual history walk + `difflib` (stdlib) | Line-provenance tracking across commits, no external deps |
| A directory-walking helper package | `os.walk` (stdlib) | Recursive `add <dir>`, working-tree cleanup during `checkout`, and the packfile/index rebuild during `gc` |
