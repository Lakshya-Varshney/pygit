# pygit_single.py — Single-file build for the hackathon's Single File bonus (+5, Hard).
# This is a mechanical concatenation of the pygit/ package into one file.
# The modular pygit/ package remains the primary implementation that the test suite exercises.
# This file is fully self-contained: `python3 pygit_single.py <command>` with no build step.

import argparse
import configparser
import datetime
import difflib
import fnmatch
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import sys
import time
import uuid
import zlib
from pathlib import Path

# ============================================================================
# objects.py
# ============================================================================


def _repo_objects_dir(repo_root=None):
    """Get the .pygit/objects directory path."""
    if repo_root is None:
        repo_root = Path.cwd()
    else:
        repo_root = Path(repo_root)
    objects_dir = repo_root / ".pygit" / "objects"
    objects_dir.mkdir(parents=True, exist_ok=True)
    return objects_dir


def hash_object(data, obj_type, repo_root=None):
    """Hash data and store it as a zlib-compressed object."""
    if isinstance(data, str):
        data = data.encode("utf-8")

    header = f"{obj_type} {len(data)}\0".encode()
    store = header + data

    sha = hashlib.sha256(store).hexdigest()
    compressed = zlib.compress(store)

    objects_dir = _repo_objects_dir(repo_root)
    obj_dir = objects_dir / sha[:2]
    obj_dir.mkdir(exist_ok=True)
    obj_path = obj_dir / sha[2:]
    obj_path.write_bytes(compressed)

    return sha


def read_object(sha, repo_root=None):
    """Read and decompress an object by its SHA."""
    objects_dir = _repo_objects_dir(repo_root)
    obj_path = objects_dir / sha[:2] / sha[2:]

    if obj_path.exists():
        compressed = obj_path.read_bytes()
        store = zlib.decompress(compressed)
        null_idx = store.index(b"\0")
        header = store[:null_idx].decode()
        obj_type = header.split()[0]
        content = store[null_idx + 1:]
        return obj_type, content

    pack_dir = objects_dir / "pack"
    if pack_dir.exists():
        for json_file in pack_dir.glob("*.json"):
            try:
                index_data = json.loads(json_file.read_text())
                if sha in index_data:
                    pack_file = json_file.with_suffix(".pack")
                    offset = index_data[sha]
                    with open(pack_file, "rb") as f:
                        f.seek(offset)
                        compressed = f.read()
                    store = zlib.decompress(compressed)
                    null_idx = store.index(b"\0")
                    header = store[:null_idx].decode()
                    obj_type = header.split()[0]
                    content = store[null_idx + 1:]
                    return obj_type, content
            except Exception:
                pass

    raise FileNotFoundError(f"Object {sha} not found")


def serialize_blob(data):
    """Serialize blob data. Blob is just raw content."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return data


def deserialize_blob(raw):
    """Deserialize blob data."""
    return ("blob", raw)


def serialize_tree(entries):
    """Serialize a tree object from entry list."""
    sorted_entries = sorted(entries, key=lambda e: e[1])

    parts = []
    for mode, name, sha in sorted_entries:
        if isinstance(name, str):
            name = name.encode("utf-8")
        raw_sha = bytes.fromhex(sha)
        parts.append(f"{mode} ".encode() + name + b"\0" + raw_sha)

    return b"".join(parts)


def deserialize_tree(raw):
    """Deserialize a tree object."""
    entries = []
    i = 0
    while i < len(raw):
        space_idx = raw.index(b" ", i)
        mode = raw[i:space_idx].decode()

        null_idx = raw.index(b"\0", space_idx)
        name = raw[space_idx + 1:null_idx].decode()

        sha_raw = raw[null_idx + 1:null_idx + 33]
        sha_hex = sha_raw.hex()

        entries.append((mode, name, sha_hex))
        i = null_idx + 33

    return entries


def serialize_commit(tree_sha, parents, author, committer, epoch, message):
    """Serialize a commit object."""
    lines = []
    lines.append(f"tree {tree_sha}")
    for parent in parents:
        lines.append(f"parent {parent}")
    lines.append(f"author {author} {epoch}")
    lines.append(f"committer {committer} {epoch}")
    lines.append("")
    lines.append(message)

    return "\n".join(lines).encode("utf-8")


def deserialize_commit(raw):
    """Deserialize a commit object."""
    text = raw.decode("utf-8")
    lines = text.split("\n")

    result = {
        "tree": None,
        "parents": [],
        "author": None,
        "committer": None,
        "author_epoch": 0,
        "committer_epoch": 0,
        "message": "",
    }

    i = 0
    for i, line in enumerate(lines):
        if line.startswith("tree "):
            result["tree"] = line[5:]
        elif line.startswith("parent "):
            result["parents"].append(line[7:])
        elif line.startswith("author "):
            parts = line[7:].rsplit(" ", 1)
            result["author"] = parts[0]
            result["author_epoch"] = int(parts[1])
        elif line.startswith("committer "):
            parts = line[10:].rsplit(" ", 1)
            result["committer"] = parts[0]
            result["committer_epoch"] = int(parts[1])
        elif line == "":
            break

    result["message"] = "\n".join(lines[i + 1:]).strip()
    return result


def serialize_tag(object_sha, object_type, tagger, tag_name, epoch, message):
    """Serialize a tag object."""
    lines = []
    lines.append(f"object {object_sha}")
    lines.append(f"type {object_type}")
    lines.append(f"tag {tag_name}")
    lines.append(f"tagger {tagger} {epoch}")
    lines.append("")
    lines.append(message)

    return "\n".join(lines).encode("utf-8")


def deserialize_tag(raw):
    """Deserialize a tag object."""
    text = raw.decode("utf-8")
    lines = text.split("\n")

    result = {
        "object": None,
        "type": None,
        "tag": None,
        "tagger": None,
        "tagger_epoch": 0,
        "message": "",
    }

    i = 0
    for i, line in enumerate(lines):
        if line.startswith("object "):
            result["object"] = line[7:]
        elif line.startswith("type "):
            result["type"] = line[5:]
        elif line.startswith("tag "):
            result["tag"] = line[4:]
        elif line.startswith("tagger "):
            parts = line[7:].rsplit(" ", 1)
            result["tagger"] = parts[0]
            result["tagger_epoch"] = int(parts[1])
        elif line == "":
            break

    result["message"] = "\n".join(lines[i + 1:]).strip()
    return result


# ============================================================================
# repository.py
# ============================================================================


class Repository:
    """Represents a pygit repository."""

    def __init__(self, path="."):
        self.root = Path(path).resolve()
        self.git_dir = self.root / ".pygit"

    def init(self):
        """Create .pygit/ directory structure."""
        dirs = [
            self.git_dir / "objects",
            self.git_dir / "objects" / "pack",
            self.git_dir / "refs" / "heads",
            self.git_dir / "refs" / "tags",
            self.git_dir / "refs" / "remotes",
            self.git_dir / "logs",
            self.git_dir / "logs" / "refs",
            self.git_dir / "logs" / "refs" / "heads",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

        head_file = self.git_dir / "HEAD"
        if not head_file.exists():
            head_file.write_text("ref: refs/heads/main\n")

        config_file = self.git_dir / "config"
        if not config_file.exists():
            config = configparser.ConfigParser()
            with config_file.open("w") as f:
                config.write(f)

        index_file = self.git_dir / "index"
        if not index_file.exists():
            index_file.write_text("[]")

        stash_file = self.git_dir / "stash"
        if not stash_file.exists():
            stash_file.write_text("[]")

        return self

    def get_head(self):
        """Read HEAD content."""
        head_file = self.git_dir / "HEAD"
        return head_file.read_text().strip()

    def set_head(self, target, command=""):
        old_head_raw = self.get_head()
        head_file = self.git_dir / "HEAD"
        head_file.write_text(target + "\n")
        if command:
            if old_head_raw.startswith("ref: "):
                old_ref = old_head_raw.split("ref: ")[1].strip()
                try:
                    old_head = self.get_ref(old_ref)
                except FileNotFoundError:
                    old_head = "0" * 64
            else:
                old_head = old_head_raw
            new_sha = target if not target.startswith("ref: ") else ""
            self.append_reflog(old_head, new_sha, command)

    def set_head_detached(self, sha):
        """Set HEAD to a raw SHA (detached state)."""
        head_file = self.git_dir / "HEAD"
        head_file.write_text(sha + "\n")

    def append_reflog(self, old_sha, new_sha, command):
        """Append an entry to logs/HEAD."""
        reflog_dir = self.git_dir / "logs"
        reflog_dir.mkdir(exist_ok=True)
        reflog_file = reflog_dir / "HEAD"

        timestamp = int(time.time())
        line = f"{old_sha} {new_sha} {command} {timestamp}\n"

        with open(reflog_file, "a") as f:
            f.write(line)

    def get_ref(self, ref_path):
        """Read a ref file and return the SHA it contains."""
        ref_file = self.root / ".pygit" / ref_path
        if not ref_file.exists():
            raise FileNotFoundError(f"Reference '{ref_path}' not found")
        return ref_file.read_text().strip()

    def set_ref(self, ref_path, sha):
        """Write a SHA to a ref file."""
        ref_file = self.root / ".pygit" / ref_path
        ref_file.parent.mkdir(parents=True, exist_ok=True)
        ref_file.write_text(sha + "\n")

    def resolve_ref(self, ref_path):
        """Follow symbolic refs to get the final SHA."""
        content = self.get_ref(ref_path)
        if content.startswith("ref: "):
            target = content[5:].strip()
            return self.resolve_ref(target)
        return content

    def get_config(self):
        """Read the config file."""
        config = configparser.ConfigParser()
        config_file = self.git_dir / "config"
        config.read(config_file)
        return config

    def set_user(self, name, email):
        """Set user identity in config."""
        config = self.get_config()
        if not config.has_section("user"):
            config.add_section("user")
        config.set("user", "name", name)
        config.set("user", "email", email)
        with open(self.git_dir / "config", "w") as f:
            config.write(f)

    def get_user(self):
        """Get user identity from config."""
        config = self.get_config()
        return config.get("user", "name"), config.get("user", "email")

    def get_author_string(self):
        """Get author string from config, falling back to placeholder."""
        try:
            name, email = self.get_user()
            return f"{name} <{email}>"
        except Exception:
            return "Unknown <unknown@example.com>"

    def set_config_value(self, key, value):
        """Set a config value. Key format: section.option (e.g. user.name)."""
        config = self.get_config()
        parts = key.split(".", 1)
        if len(parts) != 2:
            raise ValueError(f"Key must be in section.option format: {key}")
        section, option = parts
        if not config.has_section(section):
            config.add_section(section)
        config.set(section, option, value)
        with open(self.git_dir / "config", "w") as f:
            config.write(f)

    def resolve_sha_prefix(self, prefix):
        """Resolve an abbreviated sha prefix to a full sha."""
        prefix = prefix.lower()

        if len(prefix) == 64 and all(c in "0123456789abcdef" for c in prefix):
            return prefix

        if len(prefix) < 4:
            raise ValueError(
                f"error: short sha '{prefix}' is too short (minimum 4 characters)"
            )

        if not all(c in "0123456789abcdef" for c in prefix):
            raise ValueError(f"error: '{prefix}' is not a valid sha prefix")

        matches = []

        objects_dir = self.git_dir / "objects"
        if objects_dir.exists():
            if len(prefix) >= 2:
                subdir = objects_dir / prefix[:2]
                if subdir.exists():
                    for f in subdir.iterdir():
                        if f.is_file():
                            candidate = prefix[:2] + f.name
                            if candidate.startswith(prefix):
                                matches.append(candidate)
            else:
                for subdir in objects_dir.iterdir():
                    if subdir.is_dir() and len(subdir.name) == 2:
                        for f in subdir.iterdir():
                            if f.is_file():
                                candidate = subdir.name + f.name
                                if candidate.startswith(prefix):
                                    matches.append(candidate)

        pack_dir = objects_dir / "pack"
        if pack_dir.exists():
            for json_file in pack_dir.glob("*.json"):
                try:
                    index_data = json.loads(json_file.read_text())
                    for sha in index_data:
                        if sha.startswith(prefix):
                            if sha not in matches:
                                matches.append(sha)
                except Exception:
                    pass

        if len(matches) == 0:
            raise ValueError(f"error: no object matches prefix '{prefix}'")
        elif len(matches) > 1:
            raise ValueError(
                f"error: short sha '{prefix}' is ambiguous, matches multiple objects"
            )

        return matches[0]

    def add_remote(self, name, address):
        """Add a remote to config."""
        config = self.get_config()
        section = f'remote "{name}"'
        if not config.has_section(section):
            config.add_section(section)
        config.set(section, "address", address)
        with open(self.git_dir / "config", "w") as f:
            config.write(f)

    def get_remote(self, name):
        """Get remote address from config."""
        config = self.get_config()
        section = f'remote "{name}"'
        return config.get(section, "address")

    def walk_working_tree(self):
        """Walk the working tree, excluding .pygit/."""
        results = []
        for root, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d != ".pygit"]
            root_path = Path(root)
            for fname in files:
                full = root_path / fname
                rel = full.relative_to(self.root)
                mtime = os.path.getmtime(full)
                results.append((str(rel), mtime))
        return results

    def get_working_tree_files(self):
        """Get set of all files in working tree (excluding .pygit/)."""
        files = set()
        for root, dirs, filenames in os.walk(self.root):
            dirs[:] = [d for d in dirs if d != ".pygit"]
            root_path = Path(root)
            for fname in filenames:
                full = root_path / fname
                rel = full.relative_to(self.root)
                files.add(str(rel))
        return files

    def build_tree_from_index(self, index):
        """Build tree objects bottom-up from index entries."""
        entries = index.get_entries()
        if not entries:
            tree_data = serialize_tree([])
            return hash_object(tree_data, "tree", self.root)

        tree_map = {}

        for entry in entries:
            path = entry["path"]
            parts = Path(path).parts

            if len(parts) == 1:
                tree_map.setdefault("", []).append(
                    (entry["mode"], parts[0], entry["sha"])
                )
            else:
                dir_path = str(Path(*parts[:-1]))
                tree_map.setdefault(dir_path, []).append(
                    (entry["mode"], parts[-1], entry["sha"])
                )

        dir_shas = {}
        for dir_path in sorted(tree_map.keys(), reverse=True):
            entries_for_tree = list(tree_map[dir_path])

            for child_dir in list(dir_shas.keys()):
                if child_dir.startswith(dir_path + "/") or (
                    dir_path == "" and "/" in child_dir
                ):
                    child_name = child_dir.split("/")[-1] if "/" in child_dir else child_dir
                    entries_for_tree.append(("40000", child_name, dir_shas[child_dir]))

            tree_data = serialize_tree(entries_for_tree)
            dir_shas[dir_path] = hash_object(tree_data, "tree", self.root)

        root_entries = list(tree_map.get("", []))
        for child_dir, child_sha in dir_shas.items():
            if child_dir and "/" not in child_dir:
                root_entries.append(("40000", child_dir, child_sha))

        root_tree_data = serialize_tree(root_entries)
        return hash_object(root_tree_data, "tree", self.root)

    def get_tree_entries(self, commit_sha):
        """Get all file entries reachable from a commit's tree."""
        obj_type, data = read_object(commit_sha, self.root)
        if obj_type != "commit":
            raise ValueError(f"Expected commit, got {obj_type}")
        commit = deserialize_commit(data)
        return self.get_tree_entries_from_tree(commit["tree"])

    def get_tree_entries_from_tree(self, tree_sha, prefix=""):
        """Recursively get all file entries from a tree object."""
        obj_type, data = read_object(tree_sha, self.root)
        entries = deserialize_tree(data)

        result = []
        for mode, name, sha in entries:
            full_path = f"{prefix}/{name}" if prefix else name
            if mode == "40000":
                result.extend(self.get_tree_entries_from_tree(sha, full_path))
            else:
                result.append({"path": full_path, "sha": sha, "mode": mode})

        return result

    def get_file_from_commit(self, commit_sha, file_path):
        """Get file content from a commit."""
        entries = self.get_tree_entries(commit_sha)
        for entry in entries:
            if entry["path"] == file_path:
                _, content = read_object(entry["sha"], self.root)
                return content
        raise FileNotFoundError(f"File '{file_path}' not found in commit")

    def checkout_tree(self, tree_sha, old_tracked=None):
        entries = self.get_tree_entries_from_tree(tree_sha)
        target_paths = {e["path"] for e in entries}

        if old_tracked is not None:
            current_tracked = old_tracked
        else:
            current_tracked = set()
            head_raw = self.get_head()
            if head_raw.startswith("ref: "):
                ref_path = head_raw.split("ref: ")[1].strip()
                try:
                    head_sha = self.get_ref(ref_path)
                    head_entries = self.get_tree_entries(head_sha)
                    current_tracked = {e["path"] for e in head_entries}
                except Exception:
                    pass
            elif head_raw and head_raw != "0" * 64:
                try:
                    head_entries = self.get_tree_entries(head_raw)
                    current_tracked = {e["path"] for e in head_entries}
                except Exception:
                    pass

        for item in self.root.iterdir():
            if item.name == ".pygit":
                continue
            rel = str(item.relative_to(self.root))
            if item.is_dir():
                dir_files = set()
                for root, dirs, fnames in os.walk(item):
                    dirs[:] = [d for d in dirs if d != ".pygit"]
                    for fname in fnames:
                        full = Path(root) / fname
                        dir_files.add(str(full.relative_to(self.root)))
                if dir_files & current_tracked:
                    for f in dir_files:
                        if f not in target_paths:
                            fp = self.root / f
                            if fp.exists():
                                fp.unlink()
                stale_dirs = []
                for root, dirs, fnames in os.walk(item, topdown=False):
                    if root == item:
                        continue
                    rel_dir = str(Path(root).relative_to(self.root))
                    remaining = list(Path(root).iterdir())
                    if not remaining:
                        stale_dirs.append(root)
                for d in stale_dirs:
                    shutil.rmtree(d)
                if not any(item.iterdir()):
                    item.rmdir()
            else:
                if rel in current_tracked and rel not in target_paths:
                    item.unlink()

        for entry in entries:
            full_path = self.root / entry["path"]
            full_path.parent.mkdir(parents=True, exist_ok=True)
            _, content = read_object(entry["sha"], self.root)
            full_path.write_bytes(content)

        index = Index(self)
        index.clear()
        for entry in entries:
            index.add(entry["path"], entry["sha"], entry["mode"], 0)
        index.save()


# ============================================================================
# index.py
# ============================================================================


class Index:
    """Manages the staging area (index file)."""

    def __init__(self, repo):
        self.repo = repo
        self.index_path = repo.git_dir / "index"
        self._entries = []

    def load(self):
        """Load index from disk."""
        if self.index_path.exists():
            try:
                self._entries = json.loads(self.index_path.read_text())
            except json.JSONDecodeError:
                self._entries = []
        else:
            self._entries = []

    def save(self):
        """Save index to disk."""
        self.index_path.write_text(json.dumps(self._entries, indent=2) + "\n")

    def add(self, path, sha, mode="100644", mtime=0):
        """Add or update an entry in the index."""
        self._entries = [e for e in self._entries if e["path"] != path]
        self._entries.append({
            "path": path,
            "sha": sha,
            "mode": mode,
            "mtime": mtime,
        })

    def remove(self, path):
        """Remove an entry from the index."""
        self._entries = [e for e in self._entries if e["path"] != path]

    def get_entries(self):
        """Get all index entries."""
        return list(self._entries)

    def get_entry(self, path):
        """Get a specific entry by path."""
        for entry in self._entries:
            if entry["path"] == path:
                return entry
        return None

    def clear(self):
        """Clear all entries."""
        self._entries = []


# ============================================================================
# colors.py
# ============================================================================


RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"


def should_color(args_color=None, stream=None):
    """Determine whether to emit ANSI color codes."""
    if stream is None:
        stream = sys.stdout
    if args_color == "always":
        return True
    if args_color == "never":
        return False
    return stream.isatty()


def colorize(text, color):
    """Wrap text in ANSI color codes."""
    if not color:
        return text
    return f"{color}{text}{RESET}"


def colorize_diff_line(line, use_color):
    """Colorize a single diff output line."""
    if not use_color:
        return line
    if line.startswith("+") and not line.startswith("+++"):
        return colorize(line, GREEN)
    if line.startswith("-") and not line.startswith("---"):
        return colorize(line, RED)
    if line.startswith("@@"):
        return colorize(line, CYAN)
    return line


def colorize_status_item(text, color_type, use_color):
    """Colorize a status output item."""
    if not use_color:
        return text
    if color_type == "staged":
        return colorize(text, GREEN)
    return colorize(text, RED)


# ============================================================================
# ignore.py
# ============================================================================


def load_ignore(repo_root):
    """Load patterns from .pygitignore files."""
    repo_root = Path(repo_root)
    patterns = []

    ignore_file = repo_root / ".pygitignore"
    if ignore_file.exists():
        for line in ignore_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(line)

    return patterns


def is_ignored(path, patterns):
    """Check if a path matches any ignore pattern."""
    for pattern in patterns:
        normalized_path = path.replace("\\", "/")
        normalized_pattern = pattern.replace("\\", "/")

        if normalized_pattern.endswith("/"):
            dir_pattern = normalized_pattern.rstrip("/")
            parts = normalized_path.split("/")
            for i in range(len(parts)):
                partial = "/".join(parts[:i + 1]) + "/"
                if fnmatch.fnmatch(partial, normalized_pattern):
                    return True
                if fnmatch.fnmatch(parts[i] + "/", normalized_pattern):
                    return True
        else:
            if fnmatch.fnmatch(normalized_path, normalized_pattern):
                return True
            basename = normalized_path.split("/")[-1]
            if fnmatch.fnmatch(basename, normalized_pattern):
                return True

    return False


# ============================================================================
# diff.py
# ============================================================================


def diff_files(file_a, file_b, from_label="a", to_label="b"):
    """Compute unified diff between two files."""
    if isinstance(file_a, (str, Path)):
        if Path(file_a).exists():
            content_a = Path(file_a).read_text(errors="replace").splitlines(keepends=True)
        else:
            content_a = []
    else:
        content_a = file_a.splitlines(keepends=True) if isinstance(file_a, str) else file_a

    if isinstance(file_b, (str, Path)):
        if Path(file_b).exists():
            content_b = Path(file_b).read_text(errors="replace").splitlines(keepends=True)
        else:
            content_b = []
    else:
        content_b = file_b.splitlines(keepends=True) if isinstance(file_b, str) else file_b

    diff = difflib.unified_diff(
        content_a, content_b,
        fromfile=from_label, tofile=to_label,
        lineterm=""
    )
    return "\n".join(diff)


def diff_index_vs_working(repo, path):
    """Diff between index and working tree for a file."""
    index = Index(repo)
    index.load()
    entry = index.get_entry(path)
    if not entry:
        return ""

    full_path = repo.root / path
    if not full_path.exists():
        return f"deleted file\n--- a/{path}\n+++ /dev/null\n"

    working = full_path.read_text(errors="replace").splitlines(keepends=True)

    try:
        _, idx_data = read_object(entry["sha"], repo.root)
        idx_lines = idx_data.decode("utf-8", errors="replace").splitlines(keepends=True)
    except Exception:
        idx_lines = []

    return "\n".join(difflib.unified_diff(
        idx_lines, working,
        fromfile=f"a/{path}", tofile=f"b/{path}",
        lineterm=""
    ))


def diff_head_vs_index(repo, path):
    """Diff between HEAD and index for a file."""
    index = Index(repo)
    index.load()
    entry = index.get_entry(path)
    if not entry:
        return ""

    try:
        head = repo.get_head()
        if head.startswith("ref: "):
            ref_path = head.split("ref: ")[1].strip()
            head_sha = repo.get_ref(ref_path)
        else:
            head_sha = head.strip()
        head_content = repo.get_file_from_commit(head_sha, path)
        head_lines = head_content.decode("utf-8", errors="replace").splitlines(keepends=True)
    except Exception:
        head_lines = []

    try:
        _, idx_data = read_object(entry["sha"], repo.root)
        idx_lines = idx_data.decode("utf-8", errors="replace").splitlines(keepends=True)
    except Exception:
        idx_lines = []

    return "\n".join(difflib.unified_diff(
        head_lines, idx_lines,
        fromfile=f"a/{path}", tofile=f"b/{path}",
        lineterm=""
    ))


def blame(repo, file_path):
    """Show per-line commit attribution for a file."""
    try:
        head = repo.get_head()
        if head.startswith("ref: "):
            ref_path = head.split("ref: ")[1].strip()
            head_sha = repo.get_ref(ref_path)
        else:
            head_sha = head.strip()
    except (FileNotFoundError, ValueError):
        print("No commits yet", file=sys.stderr)
        return

    try:
        current_content = repo.get_file_from_commit(head_sha, file_path)
        current_lines = current_content.decode("utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        print(f"fatal: path '{file_path}' does not exist in the working tree", file=sys.stderr)
        return

    commit_history = []
    visited = set()
    stack = [head_sha]

    while stack:
        sha = stack.pop()
        if sha in visited:
            continue
        visited.add(sha)

        try:
            obj_type, data = read_object(sha, repo.root)
            if obj_type != "commit":
                continue
            commit = deserialize_commit(data)
            commit_history.append((sha, commit))
            for parent_sha in commit["parents"]:
                stack.append(parent_sha)
        except Exception:
            continue

    line_authors = []
    for line in current_lines:
        found = False
        for sha, commit in commit_history:
            try:
                file_content = repo.get_file_from_commit(sha, file_path)
                file_lines = file_content.decode("utf-8", errors="replace").splitlines()
                if line in file_lines:
                    author = commit.get("author", "Unknown")
                    author_name = author.split("<")[0].strip() if "<" in author else author
                    line_authors.append((sha[:7], author_name, line))
                    found = True
                    break
            except Exception:
                continue
        if not found:
            line_authors.append(("???????", "Unknown", line))

    for sha, author, line in line_authors:
        print(f"{sha} ({author:>20s}) {line}")


# ============================================================================
# diff_commits.py
# ============================================================================


def resolve_commit_ref(repo, name):
    """Resolve a name to a full sha."""
    if all(c in "0123456789abcdef" for c in name.lower()):
        try:
            return repo.resolve_sha_prefix(name)
        except ValueError:
            pass

    try:
        return repo.get_ref(f"refs/heads/{name}")
    except FileNotFoundError:
        pass

    try:
        return repo.get_ref(f"refs/tags/{name}")
    except FileNotFoundError:
        pass

    raise ValueError(f"unknown revision '{name}'")


def _get_tree_files(repo, tree_sha):
    """Get {path: entry_dict} for a tree sha."""
    if not tree_sha:
        return {}
    try:
        return {e["path"]: e for e in repo.get_tree_entries_from_tree(tree_sha)}
    except Exception:
        return {}


def diff_two_commits(repo, sha1, sha2):
    """Compute unified diff between two commits' trees."""
    _, data1 = read_object(sha1, repo.root)
    commit1 = deserialize_commit(data1)
    _, data2 = read_object(sha2, repo.root)
    commit2 = deserialize_commit(data2)

    files1 = _get_tree_files(repo, commit1["tree"])
    files2 = _get_tree_files(repo, commit2["tree"])

    all_paths = sorted(set(files1.keys()) | set(files2.keys()))
    diff_lines = []

    for path in all_paths:
        old_entry = files1.get(path)
        new_entry = files2.get(path)

        old_content = b""
        new_content = b""

        if old_entry:
            _, old_content = read_object(old_entry["sha"], repo.root)
        if new_entry:
            _, new_content = read_object(new_entry["sha"], repo.root)

        old_text = old_content.decode("utf-8", errors="replace").splitlines(keepends=True)
        new_text = new_content.decode("utf-8", errors="replace").splitlines(keepends=True)

        diff = list(difflib.unified_diff(
            old_text, new_text,
            fromfile=f"a/{path}", tofile=f"b/{path}"
        ))
        diff_lines.extend(diff)

    return diff_lines


# ============================================================================
# log_filter.py
# ============================================================================


def walk_commits(repo, sha, count=None):
    """Walk parent chain from sha, yielding (sha, commit_dict) tuples."""
    yielded = 0
    while sha:
        if count is not None and yielded >= count:
            return
        try:
            obj_type, data = read_object(sha, repo.root)
            if obj_type != "commit":
                break
            commit = deserialize_commit(data)
            yield (sha, commit)
            yielded += 1
            sha = commit["parents"][0] if commit["parents"] else None
        except Exception:
            break


def _get_blob_sha_for_path(repo, commit, path):
    """Get the blob sha for a given path in a commit's tree, or None."""
    try:
        entries = repo.get_tree_entries_from_tree(commit["tree"])
        for e in entries:
            if e["path"] == path:
                return e["sha"]
    except Exception:
        pass
    return None


def commits_that_touched_path(repo, sha, path):
    """Filter walk to only commits where the given path changed."""
    for commit_sha, commit in walk_commits(repo, sha):
        this_blob = _get_blob_sha_for_path(repo, commit, path)

        parent_blob = None
        if commit["parents"]:
            try:
                _, parent_data = read_object(commit["parents"][0], repo.root)
                parent_commit = deserialize_commit(parent_data)
                parent_blob = _get_blob_sha_for_path(repo, parent_commit, path)
            except Exception:
                pass

        if this_blob != parent_blob:
            yield (commit_sha, commit)


# ============================================================================
# merge.py
# ============================================================================


def find_merge_base(repo, commit_a, commit_b):
    """Find the common ancestor of two commits."""
    ancestors_a = set()
    stack = [commit_a]
    while stack:
        sha = stack.pop()
        if sha in ancestors_a:
            continue
        ancestors_a.add(sha)
        try:
            obj_type, data = read_object(sha, repo.root)
            if obj_type != "commit":
                continue
            commit = deserialize_commit(data)
            for parent in commit["parents"]:
                stack.append(parent)
        except Exception:
            continue

    stack = [commit_b]
    visited = set()
    while stack:
        sha = stack.pop()
        if sha in visited:
            continue
        visited.add(sha)
        if sha in ancestors_a:
            return sha
        try:
            obj_type, data = read_object(sha, repo.root)
            if obj_type != "commit":
                continue
            commit = deserialize_commit(data)
            for parent in commit["parents"]:
                stack.append(parent)
        except Exception:
            continue

    raise ValueError("No common ancestor found (unrelated histories)")


def three_way_merge(base_tree_sha, ours_tree_sha, theirs_tree_sha, repo):
    """Perform a three-way merge of two trees against a common base."""
    def get_tree_files(tree_sha):
        if not tree_sha:
            return {}
        try:
            entries = repo.get_tree_entries_from_tree(tree_sha)
            return {e["path"]: e for e in entries}
        except Exception:
            return {}

    base_files = get_tree_files(base_tree_sha)
    ours_files = get_tree_files(ours_tree_sha)
    theirs_files = get_tree_files(theirs_tree_sha)

    all_paths = set(base_files.keys()) | set(ours_files.keys()) | set(theirs_files.keys())

    merged_entries = []
    conflicts = []

    for path in sorted(all_paths):
        base_entry = base_files.get(path)
        ours_entry = ours_files.get(path)
        theirs_entry = theirs_files.get(path)

        base_sha = base_entry["sha"] if base_entry else None
        ours_sha = ours_entry["sha"] if ours_entry else None
        theirs_sha = theirs_entry["sha"] if theirs_entry else None

        if ours_sha == theirs_sha:
            if ours_sha:
                merged_entries.append({
                    "path": path,
                    "sha": ours_sha,
                    "mode": ours_entry["mode"] if ours_entry else "100644",
                })
            continue

        if ours_sha == base_sha:
            if theirs_sha:
                merged_entries.append({
                    "path": path,
                    "sha": theirs_sha,
                    "mode": theirs_entry["mode"] if theirs_entry else "100644",
                })
            continue

        if theirs_sha == base_sha:
            if ours_sha:
                merged_entries.append({
                    "path": path,
                    "sha": ours_sha,
                    "mode": ours_entry["mode"] if ours_entry else "100644",
                })
            continue

        try:
            base_content = b""
            ours_content = b""
            theirs_content = b""

            if base_sha:
                _, base_content = read_object(base_sha, repo.root)
            if ours_sha:
                _, ours_content = read_object(ours_sha, repo.root)
            if theirs_sha:
                _, theirs_content = read_object(theirs_sha, repo.root)

            base_lines = base_content.decode("utf-8", errors="replace").splitlines(keepends=True)
            ours_lines = ours_content.decode("utf-8", errors="replace").splitlines(keepends=True)
            theirs_lines = theirs_content.decode("utf-8", errors="replace").splitlines(keepends=True)

            sm_ours = difflib.SequenceMatcher(None, base_lines, ours_lines)
            sm_theirs = difflib.SequenceMatcher(None, base_lines, theirs_lines)

            merged_lines = []
            has_conflict = False

            ours_ops = [(op, i1, i2, j1, j2) for op, i1, i2, j1, j2 in sm_ours.get_opcodes() if op != 'equal']
            theirs_ops = [(op, i1, i2, j1, j2) for op, i1, i2, j1, j2 in sm_theirs.get_opcodes() if op != 'equal']

            conflict = False
            for o_op in ours_ops:
                for t_op in theirs_ops:
                    o_start, o_end = o_op[1], o_op[2]
                    t_start, t_end = t_op[1], t_op[2]
                    if o_start < t_end and t_start < o_end:
                        conflict = True
                        break
                if conflict:
                    break

            if conflict:
                merged_lines = []
                merged_lines.append(f"<<<<<<< HEAD\n")
                merged_lines.extend(ours_lines)
                merged_lines.append(f"=======\n")
                merged_lines.extend(theirs_lines)
                merged_lines.append(f">>>>>>> {theirs_sha[:7] if theirs_sha else 'theirs'}\n")
                has_conflict = True
            else:
                result = list(base_lines)
                for op, i1, i2, j1, j2 in reversed(sm_ours.get_opcodes()):
                    if op == 'replace':
                        result[i1:i2] = ours_lines[j1:j2]
                    elif op == 'delete':
                        result[i1:i2] = []
                    elif op == 'insert':
                        result[i1:i1] = ours_lines[j1:j2]

                sm_result = difflib.SequenceMatcher(None, base_lines, result)
                for op, i1, i2, j1, j2 in sm_result.get_opcodes():
                    if op == 'replace':
                        result[i1:i2] = theirs_lines[j1:j2]
                    elif op == 'delete':
                        result[i1:i2] = []
                    elif op == 'insert':
                        result[i1:i1] = theirs_lines[j1:j2]

                merged_lines = result

            merged_content = "".join(merged_lines).encode("utf-8")
            merged_sha = hash_object(merged_content, "blob", repo.root)
            mode = ours_entry["mode"] if ours_entry else (theirs_entry["mode"] if theirs_entry else "100644")
            merged_entries.append({"path": path, "sha": merged_sha, "mode": mode})

            if has_conflict:
                conflicts.append(path)

        except Exception as e:
            conflicts.append(path)
            if ours_sha:
                merged_entries.append({"path": path, "sha": ours_sha, "mode": ours_entry["mode"] if ours_entry else "100644"})

    tree_entries = [(e["mode"], e["path"], e["sha"]) for e in merged_entries]
    tree_data = serialize_tree(tree_entries)
    merged_tree_sha = hash_object(tree_data, "tree", repo.root)

    return merged_tree_sha, conflicts


def merge_branch(repo, branch_name):
    """Merge a branch into the current branch."""
    head = repo.get_head()
    if not head.startswith("ref: "):
        raise ValueError("HEAD is detached, cannot merge")
    current_ref = head.split("ref: ")[1].strip()
    current_sha = repo.get_ref(current_ref)

    try:
        target_sha = repo.get_ref(f"refs/heads/{branch_name}")
    except FileNotFoundError:
        raise ValueError(f"branch '{branch_name}' not found")

    if current_sha == target_sha:
        print("Already up to date.")
        return

    try:
        base_sha = find_merge_base(repo, current_sha, target_sha)
    except ValueError as e:
        raise ValueError(str(e))

    if base_sha == current_sha:
        repo.set_ref(current_ref, target_sha)
        repo.append_reflog(current_sha, target_sha, "merge")
        print(f"Fast-forward to {target_sha[:7]}")
        return

    if base_sha == target_sha:
        print("Already up to date.")
        return

    base_commit = deserialize_commit(read_object(base_sha, repo.root)[1])
    ours_commit = deserialize_commit(read_object(current_sha, repo.root)[1])
    theirs_commit = deserialize_commit(read_object(target_sha, repo.root)[1])

    merged_tree_sha, conflicts = three_way_merge(
        base_commit["tree"], ours_commit["tree"], theirs_commit["tree"], repo
    )

    if conflicts:
        for path in conflicts:
            try:
                entries = repo.get_tree_entries_from_tree(merged_tree_sha)
                for entry in entries:
                    if entry["path"] == path:
                        full = repo.root / path
                        full.parent.mkdir(parents=True, exist_ok=True)
                        _, content = read_object(entry["sha"], repo.root)
                        full.write_bytes(content)
            except Exception:
                pass
        print(f"CONFLICT: Merge conflict in {', '.join(conflicts)}")
        print("Automatic merge failed; fix conflicts and then commit the result.")
        sys.exit(1)

    author = repo.get_author_string()
    epoch = int(time.time())

    commit_data = serialize_commit(
        merged_tree_sha, [current_sha, target_sha],
        author, author, epoch,
        f"Merge branch '{branch_name}'"
    )
    merge_sha = hash_object(commit_data, "commit", repo.root)

    repo.set_ref(current_ref, merge_sha)
    repo.append_reflog(current_sha, merge_sha, "merge")
    print(f"Merge made by the 'ort' strategy.")


def cherry_pick(repo, commit_sha):
    """Apply a commit's changes to the current branch."""
    head = repo.get_head()
    if not head.startswith("ref: "):
        raise ValueError("HEAD is detached, cannot cherry-pick")
    current_ref = head.split("ref: ")[1].strip()
    current_sha = repo.get_ref(current_ref)

    obj_type, data = read_object(commit_sha, repo.root)
    if obj_type != "commit":
        raise ValueError(f"Object {commit_sha} is not a commit")
    target_commit = deserialize_commit(data)

    if target_commit["parents"]:
        parent_sha = target_commit["parents"][0]
        parent_commit = deserialize_commit(read_object(parent_sha, repo.root)[1])
        base_tree = parent_commit["tree"]
    else:
        base_tree = hash_object(serialize_tree([]), "tree", repo.root)

    current_commit = deserialize_commit(read_object(current_sha, repo.root)[1])
    current_tree = current_commit["tree"]

    merged_sha, conflicts = three_way_merge(
        base_tree, current_tree, target_commit["tree"], repo
    )

    if conflicts:
        raise ValueError(f"Conflicts in: {', '.join(conflicts)}")

    author = repo.get_author_string()
    epoch = int(time.time())

    commit_data = serialize_commit(
        merged_sha, [current_sha],
        author, author, epoch,
        f"cherry-pick: {target_commit['message']}"
    )
    new_sha = hash_object(commit_data, "commit", repo.root)

    repo.set_ref(current_ref, new_sha)
    repo.append_reflog(current_sha, new_sha, "cherry-pick")
    repo.checkout_tree(merged_sha)
    print(f"[main {new_sha[:7]}] {target_commit['message']}")


def rebase(repo, target_branch):
    """Replay current branch commits on top of another branch."""
    head = repo.get_head()
    if not head.startswith("ref: "):
        raise ValueError("HEAD is detached, cannot rebase")
    current_ref = head.split("ref: ")[1].strip()
    current_sha = repo.get_ref(current_ref)

    try:
        target_sha = repo.get_ref(f"refs/heads/{target_branch}")
    except FileNotFoundError:
        raise ValueError(f"branch '{target_branch}' not found")

    try:
        base_sha = find_merge_base(repo, current_sha, target_sha)
    except ValueError:
        raise ValueError("No common ancestor found")

    if base_sha == current_sha:
        print("Already on top of the target branch.")
        return

    commits_to_replay = []
    stack = [current_sha]
    visited = set()
    while stack:
        sha = stack.pop()
        if sha in visited or sha == base_sha:
            continue
        visited.add(sha)
        commits_to_replay.append(sha)
        try:
            commit = deserialize_commit(read_object(sha, repo.root)[1])
            for parent in commit["parents"]:
                stack.append(parent)
        except Exception:
            continue

    commits_to_replay.reverse()

    new_base = target_sha
    for old_sha in commits_to_replay:
        old_commit = deserialize_commit(read_object(old_sha, repo.root)[1])

        if old_commit["parents"]:
            parent_commit = deserialize_commit(read_object(old_commit["parents"][0], repo.root)[1])
            base_tree = parent_commit["tree"]
        else:
            base_tree = hash_object(serialize_tree([]), "tree", repo.root)

        new_base_commit = deserialize_commit(read_object(new_base, repo.root)[1])

        merged_sha, conflicts = three_way_merge(
            base_tree, new_base_commit["tree"], old_commit["tree"], repo
        )

        if conflicts:
            raise ValueError(f"Conflict replaying {old_sha[:7]}: {', '.join(conflicts)}")

        author = repo.get_author_string()
        epoch = int(time.time())

        commit_data = serialize_commit(
            merged_sha, [new_base],
            author, author, epoch,
            old_commit["message"]
        )
        new_sha = hash_object(commit_data, "commit", repo.root)
        new_base = new_sha

    repo.set_ref(current_ref, new_base)
    repo.append_reflog(current_sha, new_base, "rebase")
    new_base_commit = deserialize_commit(read_object(new_base, repo.root)[1])
    repo.checkout_tree(new_base_commit["tree"])
    print(f"Successfully rebased and updated refs/heads/{current_ref.split('/')[-1]}.")


def revert(repo, commit_sha):
    """Create a commit that undoes a previous commit."""
    head = repo.get_head()
    if not head.startswith("ref: "):
        raise ValueError("HEAD is detached, cannot revert")
    current_ref = head.split("ref: ")[1].strip()
    current_sha = repo.get_ref(current_ref)

    obj_type, data = read_object(commit_sha, repo.root)
    if obj_type != "commit":
        raise ValueError(f"Object {commit_sha} is not a commit")
    target_commit = deserialize_commit(data)

    if target_commit["parents"]:
        parent_commit = deserialize_commit(read_object(target_commit["parents"][0], repo.root)[1])
        revert_tree = parent_commit["tree"]
    else:
        revert_tree = hash_object(serialize_tree([]), "tree", repo.root)

    author = repo.get_author_string()
    epoch = int(time.time())

    commit_data = serialize_commit(
        revert_tree, [current_sha],
        author, author, epoch,
        f"Revert \"{target_commit['message']}\""
    )
    new_sha = hash_object(commit_data, "commit", repo.root)

    repo.set_ref(current_ref, new_sha)
    repo.append_reflog(current_sha, new_sha, "revert")
    repo.checkout_tree(revert_tree)
    print(f"[main {new_sha[:7]}] Revert \"{target_commit['message']}\"")


# ============================================================================
# stash.py
# ============================================================================


class StashEntry:
    """Represents a stashed state."""

    def __init__(self, index_entries, working_files, ref=None):
        self.index_entries = index_entries
        self.working_files = working_files
        self.ref = ref
        self.timestamp = int(time.time())


def stash_push(repo):
    """Save current index and working-tree diff as a stash entry."""
    index = Index(repo)
    index.load()

    working_files = {}
    index_entries = index.get_entries()

    for entry in index_entries:
        path = entry["path"]
        full = repo.root / path
        if full.exists():
            working_files[path] = full.read_bytes()

    stash_data = {
        "index": index_entries,
        "working_files": {k: v.decode("latin-1") for k, v in working_files.items()},
        "timestamp": int(time.time()),
        "ref": repo.get_head(),
    }

    stash_file = repo.git_dir / "stash"
    try:
        stash_list = json.loads(stash_file.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        stash_list = []

    stash_list.append(stash_data)
    stash_file.write_text(json.dumps(stash_list, indent=2) + "\n")

    try:
        head = repo.get_head()
        if head.startswith("ref: "):
            ref_path = head.split("ref: ")[1].strip()
            head_sha = repo.get_ref(ref_path)
        else:
            head_sha = head.strip()

        commit = deserialize_commit(read_object(head_sha, repo.root)[1])
        repo.checkout_tree(commit["tree"])
    except Exception:
        pass

    index.clear()
    index.save()


def stash_pop(repo):
    """Restore the most recent stash entry."""
    stash_file = repo.git_dir / "stash"
    if not stash_file.exists():
        print("No stash entries found.", file=sys.stderr)
        return

    try:
        stash_list = json.loads(stash_file.read_text())
    except json.JSONDecodeError:
        print("No stash entries found.", file=sys.stderr)
        return

    if not stash_list:
        print("No stash entries found.", file=sys.stderr)
        return

    entry = stash_list.pop(0)

    for path, content_str in entry.get("working_files", {}).items():
        full = repo.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(content_str.encode("latin-1"))

    index = Index(repo)
    index.clear()
    for ie in entry.get("index", []):
        index.add(ie["path"], ie["sha"], ie.get("mode", "100644"), ie.get("mtime", 0))
    index.save()

    stash_file.write_text(json.dumps(stash_list, indent=2) + "\n")


def stash_list(repo):
    """List all stash entries."""
    stash_file = repo.git_dir / "stash"
    if not stash_file.exists():
        return

    try:
        stash_list = json.loads(stash_file.read_text())
    except json.JSONDecodeError:
        return

    for i, entry in enumerate(stash_list):
        timestamp = entry.get("timestamp", 0)
        dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        print(f"stash@{{{i}}}: WIP on {entry.get('ref', 'HEAD')}:{dt}")


# ============================================================================
# pack.py
# ============================================================================


class PackWriter:
    """Writes objects to a packfile with a JSON sidecar index."""

    def __init__(self, repo):
        self.repo = repo
        self.pack_dir = repo.git_dir / "objects" / "pack"
        self.pack_dir.mkdir(parents=True, exist_ok=True)
        self.objects = []
        self.offsets = {}

    def add_object(self, sha):
        """Add an object to the packfile."""
        if sha in self.offsets:
            return

        try:
            obj_type, data = read_object(sha, self.repo.root)
        except FileNotFoundError:
            return

        header = f"{obj_type} {len(data)}\0".encode()
        store = header + data
        compressed = zlib.compress(store)

        offset = sum(len(c) for _, c in self.objects)
        self.offsets[sha] = offset
        self.objects.append((sha, compressed))

    def write_pack(self):
        """Write the packfile and JSON sidecar index."""
        pack_id = str(uuid.uuid4())[:8]
        pack_path = self.pack_dir / f"pack-{pack_id}.pack"
        index_path = self.pack_dir / f"pack-{pack_id}.json"

        with open(pack_path, "wb") as f:
            for sha, compressed in self.objects:
                f.write(compressed)

        index_data = {sha: offset for sha, offset in self.offsets.items()}
        index_path.write_text(json.dumps(index_data, indent=2) + "\n")

        return pack_path


class PackReader:
    """Reads objects from a packfile using its JSON sidecar index."""

    def __init__(self, repo):
        self.repo = repo
        self.pack_dir = repo.git_dir / "objects" / "pack"
        self._packs = None

    def _load_packs(self):
        """Load all packfile indices."""
        if self._packs is not None:
            return self._packs

        self._packs = []
        if not self.pack_dir.exists():
            return self._packs

        for json_file in self.pack_dir.glob("*.json"):
            pack_file = json_file.with_suffix(".pack")
            if pack_file.exists():
                index = json.loads(json_file.read_text())
                self._packs.append((pack_file, index))

        return self._packs

    def read_object(self, sha):
        """Read an object from packfiles."""
        for pack_file, index in self._load_packs():
            if sha in index:
                offset = index[sha]
                return self._read_from_pack(pack_file, offset)
        return None

    def _read_from_pack(self, pack_file, offset):
        """Read and decompress an object from a packfile at given offset."""
        with open(pack_file, "rb") as f:
            f.seek(offset)
            compressed = f.read()

        store = zlib.decompress(compressed)
        null_idx = store.index(b"\0")
        header = store[:null_idx].decode()
        obj_type = header.split()[0]
        content = store[null_idx + 1:]
        return obj_type, content


def find_reachable_objects(repo):
    """Find all objects reachable from refs and reflogs."""
    reachable = set()

    def walk_commit(sha):
        if sha in reachable:
            return
        reachable.add(sha)
        try:
            obj_type, data = read_object(sha, repo.root)
            if obj_type == "commit":
                commit = deserialize_commit(data)
                walk_tree(commit["tree"])
                for parent in commit["parents"]:
                    walk_commit(parent)
        except Exception:
            pass

    def walk_tree(sha):
        if sha in reachable:
            return
        reachable.add(sha)
        try:
            obj_type, data = read_object(sha, repo.root)
            if obj_type == "tree":
                entries = deserialize_tree(data)
                for mode, name, entry_sha in entries:
                    if mode == "40000":
                        walk_tree(entry_sha)
                    else:
                        reachable.add(entry_sha)
        except Exception:
            pass

    refs_dir = repo.git_dir / "refs"
    if refs_dir.exists():
        for ref_file in refs_dir.rglob("*"):
            if ref_file.is_file():
                try:
                    sha = ref_file.read_text().strip()
                    if len(sha) == 64:
                        try:
                            obj_type, _ = read_object(sha, repo.root)
                            if obj_type == "tag":
                                _, tag_data = read_object(sha, repo.root)
                                tag = deserialize_tag(tag_data)
                                walk_commit(tag["object"])
                            else:
                                walk_commit(sha)
                        except Exception:
                            walk_commit(sha)
                except Exception:
                    pass

    logs_dir = repo.git_dir / "logs"
    if logs_dir.exists():
        for log_file in logs_dir.rglob("*"):
            if log_file.is_file():
                try:
                    for line in log_file.read_text().splitlines():
                        parts = line.split()
                        if len(parts) >= 2:
                            for sha in parts[:2]:
                                if len(sha) == 64:
                                    try:
                                        walk_commit(sha)
                                    except Exception:
                                        pass
                except Exception:
                    pass

    return reachable


def gc(repo):
    """Garbage collection: pack loose objects, delete unreachable."""
    reachable = find_reachable_objects(repo)

    pack_writer = PackWriter(repo)
    for sha in reachable:
        pack_writer.add_object(sha)

    if pack_writer.objects:
        pack_writer.write_pack()

    objects_dir = repo.git_dir / "objects"
    if objects_dir.exists():
        for obj_dir in objects_dir.iterdir():
            if obj_dir.is_dir() and len(obj_dir.name) == 2:
                for obj_file in obj_dir.iterdir():
                    if obj_file.is_file():
                        sha = obj_dir.name + obj_file.stem
                        if sha in reachable:
                            obj_file.unlink()
                if not any(obj_dir.iterdir()):
                    obj_dir.rmdir()

    if objects_dir.exists():
        for obj_dir in objects_dir.iterdir():
            if obj_dir.is_dir() and len(obj_dir.name) == 2:
                for obj_file in obj_dir.iterdir():
                    if obj_file.is_file():
                        sha = obj_dir.name + obj_file.stem
                        if sha not in reachable:
                            obj_file.unlink()
                if not any(obj_dir.iterdir()):
                    obj_dir.rmdir()


# ============================================================================
# clean.py
# ============================================================================


def _get_index_paths(repo):
    """Get set of paths currently in the index."""
    index = Index(repo)
    index.load()
    return {e["path"] for e in index.get_entries()}


def _get_head_tree_paths(repo):
    """Get set of paths in the HEAD commit's tree."""
    head_paths = set()
    try:
        head = repo.get_head()
        if head.startswith("ref: "):
            ref_path = head.split("ref: ")[1].strip()
            head_sha = repo.get_ref(ref_path)
        else:
            head_sha = head.strip()
        entries = repo.get_tree_entries(head_sha)
        head_paths = {e["path"] for e in entries}
    except Exception:
        pass
    return head_paths


def _dir_has_tracked_files(dir_path, tracked):
    """Check if any file at any depth inside dir_path is tracked."""
    for root, dirs, filenames in os.walk(dir_path):
        dirs[:] = [d for d in dirs if d != ".pygit"]
        for fname in filenames:
            if fname.startswith(".pygit"):
                continue
            rel = str(Path(root).joinpath(fname).relative_to(dir_path.parent)).replace("\\", "/")
            if rel in tracked:
                return True
    return False


def get_untracked_files(repo, include_ignored=False, include_dirs=False):
    """Return list of untracked file paths (relative to repo root)."""
    index_paths = _get_index_paths(repo)
    head_paths = _get_head_tree_paths(repo)
    tracked = index_paths | head_paths

    patterns = load_ignore(repo.root) if not include_ignored else []
    result = []

    for root, dirs, filenames in os.walk(repo.root):
        dirs[:] = [d for d in dirs if d != ".pygit"]

        root_path = Path(root)
        rel_dir = str(root_path.relative_to(repo.root)).replace("\\", "/")

        if rel_dir != ".":
            has_tracked = _dir_has_tracked_files(root_path, tracked)
            if not has_tracked:
                if not include_ignored and is_ignored(rel_dir + "/", patterns):
                    continue
                if include_dirs:
                    result.append((rel_dir, True))
                dirs.clear()
                continue

        for fname in filenames:
            if fname.startswith(".pygit"):
                continue
            full = root_path / fname
            rel = str(full.relative_to(repo.root)).replace("\\", "/")

            if rel in tracked:
                continue

            if not include_ignored and is_ignored(rel, patterns):
                continue

            result.append((rel, False))

    return sorted(result)


def get_clean_targets(repo, include_ignored=False, include_dirs=False):
    """Return list of (path, is_dir) tuples for files that would be cleaned."""
    return get_untracked_files(repo, include_ignored, include_dirs)


def clean_repo(repo, dry_run=False, include_ignored=False, include_dirs=False):
    """Clean untracked files from the working tree."""
    targets = get_clean_targets(repo, include_ignored, include_dirs)
    removed = []

    for path, is_dir in targets:
        if dry_run:
            print(f"Would remove {path}")
            removed.append(path)
        else:
            full = repo.root / path
            if is_dir:
                if full.exists():
                    shutil.rmtree(full)
                    removed.append(path)
            else:
                if full.exists():
                    os.unlink(full)
                    removed.append(path)

    return removed


# ============================================================================
# network.py
# ============================================================================


def find_reachable(repo, sha):
    """Walk all objects reachable from sha (commit -> tree -> blobs/subtrees)."""
    reachable = set()
    stack = [sha]
    while stack:
        s = stack.pop()
        if s in reachable:
            continue
        reachable.add(s)
        try:
            obj_type, data = read_object(s, repo.root)
            if obj_type == "commit":
                commit = deserialize_commit(data)
                stack.append(commit["tree"])
                for parent in commit["parents"]:
                    stack.append(parent)
            elif obj_type == "tree":
                entries = deserialize_tree(data)
                for mode, name, entry_sha in entries:
                    stack.append(entry_sha)
        except Exception:
            continue
    return reachable


class SocketReader:
    def __init__(self, sock):
        self.sock = sock
        self.buf = b""

    def read_line(self):
        while b"\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        return line.decode()

    def read_exact(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            self.buf += chunk
        data, self.buf = self.buf[:n], self.buf[n:]
        return data


class Server:
    def __init__(self, repo, host="localhost", port=5000):
        self.repo = repo
        self.host = host
        self.port = port

    def start(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host, self.port))
            sock.listen(1)
            print(f"pygit server listening on {self.host}:{self.port}")

            while True:
                conn, addr = sock.accept()
                try:
                    self.handle_client(conn)
                except Exception as e:
                    print(f"Error handling client: {e}")
                finally:
                    conn.close()

    def handle_client(self, conn):
        reader = SocketReader(conn)

        line = reader.read_line()
        if line.startswith("WANT "):
            self._handle_want(conn, reader, line)
        elif line.startswith("PUSH "):
            self._handle_push(conn, reader, line)
        else:
            conn.sendall(b"ERROR: Expected WANT or PUSH command\n")

    def _handle_want(self, conn, reader, line):
        """Handle clone/fetch: server sends objects to client."""
        ref_name = line[5:].strip()
        ref_path = f"refs/heads/{ref_name}"

        try:
            tip_sha = self.repo.get_ref(ref_path)
        except FileNotFoundError:
            conn.sendall(b"ERROR: Reference not found\n")
            return

        conn.sendall(f"{tip_sha}\n".encode())

        line = reader.read_line()
        if not line.startswith("HAVE "):
            conn.sendall(b"ERROR: Expected HAVE command\n")
            return

        have_shas = set(line[5:].split()) if line[5:].strip() else set()

        reachable = self._find_reachable(tip_sha)
        missing = reachable - have_shas

        conn.sendall(f"{len(missing)}\n".encode())

        for sha in missing:
            try:
                obj_type, data = read_object(sha, self.repo.root)
                header = f"{obj_type} {len(data)}\0".encode()
                store = header + data
                compressed = zlib.compress(store)
                sha_bytes = sha.encode()
                len_bytes = struct.pack(">I", len(compressed))
                conn.sendall(sha_bytes + b"\0" + len_bytes + compressed)
            except Exception:
                continue

        update_line = reader.read_line()
        if update_line.startswith("UPDATE "):
            parts = update_line.split()
            if len(parts) == 3:
                _, update_ref, update_sha = parts
                self.repo.set_ref(f"refs/heads/{update_ref}", update_sha)

    def _handle_push(self, conn, reader, line):
        """Handle push: client sends objects to server."""
        ref_name = line[5:].strip()
        ref_path = f"refs/heads/{ref_name}"

        try:
            tip_sha = self.repo.get_ref(ref_path)
        except FileNotFoundError:
            tip_sha = None

        if tip_sha:
            conn.sendall(f"TIP {tip_sha}\n".encode())
        else:
            conn.sendall(b"TIP NONE\n")

        count_line = reader.read_line()
        if not count_line.startswith("COUNT "):
            conn.sendall(b"ERROR: Expected COUNT command\n")
            return

        count = int(count_line[6:])

        for _ in range(count):
            self._receive_object(reader)

        update_line = reader.read_line()
        if update_line.startswith("UPDATE "):
            parts = update_line.split()
            if len(parts) == 3:
                _, update_ref, update_sha = parts
                self.repo.set_ref(f"refs/heads/{update_ref}", update_sha)

        conn.sendall(b"OK\n")

    def _receive_object(self, reader):
        """Receive and store an object from the client."""
        sha_data = b""
        while True:
            byte = reader.read_exact(1)
            if byte == b"\0":
                break
            sha_data += byte

        sha = sha_data.decode()

        len_data = reader.read_exact(4)
        length = struct.unpack(">I", len_data)[0]

        compressed = reader.read_exact(length)

        store = zlib.decompress(compressed)
        null_idx = store.index(b"\0")
        header = store[:null_idx].decode()
        obj_type = header.split()[0]
        content = store[null_idx + 1:]

        hash_object(content, obj_type, self.repo.root)

    def _find_reachable(self, sha):
        return find_reachable(self.repo, sha)


class Client:
    def __init__(self, repo):
        self.repo = repo

    def clone(self, host, port, ref_name="main"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((host, port))
            reader = SocketReader(sock)

            sock.sendall(f"WANT {ref_name}\n".encode())
            tip_sha = reader.read_line()

            if tip_sha.startswith("ERROR:"):
                raise RuntimeError(tip_sha)

            sock.sendall(b"HAVE \n")

            count_line = reader.read_line()
            count = int(count_line)

            for _ in range(count):
                self._receive_object(reader)

            self.repo.set_ref(f"refs/heads/{ref_name}", tip_sha)

            commit = deserialize_commit(read_object(tip_sha, self.repo.root)[1])
            self.repo.checkout_tree(commit["tree"])

    def push(self, host, port, ref_name="main"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((host, port))
            reader = SocketReader(sock)

            ref_path = f"refs/heads/{ref_name}"
            local_sha = self.repo.get_ref(ref_path)

            sock.sendall(f"PUSH {ref_name}\n".encode())

            tip_line = reader.read_line()
            if tip_line.startswith("ERROR:"):
                raise RuntimeError(tip_line)
            if not tip_line.startswith("TIP "):
                raise RuntimeError(f"Protocol error: expected TIP, got {tip_line}")

            remote_tip = tip_line[4:].strip()
            if remote_tip == "NONE":
                remote_tip = None

            if remote_tip:
                try:
                    read_object(remote_tip, self.repo.root)
                except Exception:
                    raise RuntimeError("error: push rejected — remote has moved ahead since your last fetch; fetch first")

                try:
                    base = find_merge_base(self.repo, local_sha, remote_tip)
                    if base != remote_tip:
                        raise RuntimeError("error: push rejected — remote has commits not present locally; fetch first")
                except ValueError:
                    raise RuntimeError("error: push rejected — histories are unrelated; fetch first")

            local_reachable = self._find_reachable(local_sha)

            if remote_tip:
                remote_ancestors = self._find_reachable(remote_tip)
                to_send = local_reachable - remote_ancestors
            else:
                to_send = local_reachable

            sock.sendall(f"COUNT {len(to_send)}\n".encode())

            for sha in to_send:
                try:
                    obj_type, data = read_object(sha, self.repo.root)
                    header = f"{obj_type} {len(data)}\0".encode()
                    store = header + data
                    compressed = zlib.compress(store)
                    sha_bytes = sha.encode()
                    len_bytes = struct.pack(">I", len(compressed))
                    sock.sendall(sha_bytes + b"\0" + len_bytes + compressed)
                except Exception:
                    continue

            sock.sendall(f"UPDATE {ref_name} {local_sha}\n".encode())

            ok_line = reader.read_line()
            if ok_line.startswith("ERROR:"):
                raise RuntimeError(ok_line)
            if ok_line.strip() != "OK":
                raise RuntimeError(f"Push failed: {ok_line}")

    def fetch(self, remote_name, host, port, ref_name="main"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((host, port))
            reader = SocketReader(sock)

            sock.sendall(f"WANT {ref_name}\n".encode())
            tip_sha = reader.read_line()

            if tip_sha.startswith("ERROR:"):
                raise RuntimeError(tip_sha)

            local_shas = set()
            try:
                local_sha = self.repo.get_ref(f"refs/remotes/{remote_name}/{ref_name}")
                local_shas = self._find_reachable(local_sha)
            except FileNotFoundError:
                pass

            sock.sendall(f"HAVE {' '.join(local_shas)}\n".encode())

            count_line = reader.read_line()
            count = int(count_line)

            for _ in range(count):
                self._receive_object(reader)

            self.repo.set_ref(f"refs/remotes/{remote_name}/{ref_name}", tip_sha)

    def _receive_object(self, reader):
        sha_data = b""
        while True:
            byte = reader.read_exact(1)
            if byte == b"\0":
                break
            sha_data += byte

        sha = sha_data.decode()

        len_data = reader.read_exact(4)
        length = struct.unpack(">I", len_data)[0]

        compressed = reader.read_exact(length)

        store = zlib.decompress(compressed)
        null_idx = store.index(b"\0")
        header = store[:null_idx].decode()
        obj_type = header.split()[0]
        content = store[null_idx + 1:]

        hash_object(content, obj_type, self.repo.root)

    def _find_reachable(self, sha):
        return find_reachable(self.repo, sha)


# ============================================================================
# __main__.py (CLI)
# ============================================================================


def cmd_init(args):
    """Create .pygit/ directory structure."""
    repo = Repository(args.path or ".")
    repo.init()
    print(f"Initialized empty pygit repository in {repo.git_dir}")


def _get_current_sha(repo):
    """Get the SHA that HEAD currently points to."""
    head = repo.get_head()
    if head.startswith("ref: "):
        ref_path = head.split("ref: ")[1].strip()
        return repo.get_ref(ref_path)
    return head.strip()


def _resolve_ref(repo, name):
    """Resolve a name to a sha, trying sha prefix, then branch, then tag."""
    if all(c in "0123456789abcdef" for c in name.lower()):
        try:
            return repo.resolve_sha_prefix(name)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)

    try:
        return repo.get_ref(f"refs/heads/{name}")
    except FileNotFoundError:
        pass

    try:
        return repo.get_ref(f"refs/tags/{name}")
    except FileNotFoundError:
        pass

    print(f"error: unknown revision '{name}'", file=sys.stderr)
    sys.exit(1)


def _switch_branch(repo, branch_name, force=False):
    """Create or reset a branch at HEAD, then switch to it."""
    current_sha = _get_current_sha(repo)
    ref_path = f"refs/heads/{branch_name}"

    try:
        existing_sha = repo.get_ref(ref_path)
        if not force:
            print(f"fatal: A branch named '{branch_name}' already exists.", file=sys.stderr)
            return False
    except FileNotFoundError:
        existing_sha = None

    repo.set_ref(ref_path, current_sha)
    if existing_sha:
        repo.append_reflog(existing_sha, current_sha, "checkout")
    return True


def cmd_add(args):
    from pathlib import Path
    repo = Repository(".")
    index = Index(repo)
    index.load()
    patterns = load_ignore(repo.root)

    files_to_add = []

    for path in args.paths:
        if is_ignored(path, patterns):
            continue
        full_path = repo.root / path
        if not full_path.exists():
            print(f"fatal: pathspec '{path}' did not match any files", file=sys.stderr)
            sys.exit(1)
        if full_path.is_dir():
            for root, dirs, filenames in os.walk(full_path):
                dirs[:] = [d for d in dirs if d != ".pygit"]
                root_path = Path(root)
                for fname in filenames:
                    if fname.startswith(".pygit"):
                        continue
                    full = root_path / fname
                    rel = str(full.relative_to(repo.root))
                    if is_ignored(rel, patterns):
                        continue
                    files_to_add.append((rel, full))
        else:
            files_to_add.append((path, full_path))

    for rel, full in files_to_add:
        data = full.read_bytes()
        sha = hash_object(data, "blob", repo.root)
        mtime = os.path.getmtime(full)
        index.add(rel, sha, "100644", mtime)
    index.save()


def cmd_commit(args):
    repo = Repository(".")
    index = Index(repo)
    index.load()

    if not index.get_entries():
        print("nothing to commit (empty index)", file=sys.stderr)
        sys.exit(1)

    root_tree_sha = repo.build_tree_from_index(index)

    parent_sha = None
    try:
        head = repo.get_head()
        if not head.startswith("ref: "):
            parent_sha = head
        else:
            ref_path = head.split("ref: ")[1].strip()
            parent_sha = repo.get_ref(ref_path)
    except (FileNotFoundError, ValueError):
        pass

    if args.amend:
        if not parent_sha:
            print("error: nothing to amend", file=sys.stderr)
            sys.exit(1)
        try:
            _, parent_data = read_object(parent_sha, repo.root)
            parent_commit = deserialize_commit(parent_data)
            amend_parents = parent_commit["parents"]
            if not args.message:
                args.message = parent_commit["message"]
        except Exception:
            amend_parents = []
    else:
        if parent_sha:
            try:
                _, parent_data = read_object(parent_sha, repo.root)
                parent_commit = deserialize_commit(parent_data)
                if parent_commit["tree"] == root_tree_sha:
                    print("nothing to commit, working tree clean", file=sys.stderr)
                    sys.exit(1)
            except Exception:
                pass
        amend_parents = [parent_sha] if parent_sha else []

    if not args.message:
        print("error: commit message required (use -m or --amend)", file=sys.stderr)
        sys.exit(1)

    author = repo.get_author_string()
    committer = author
    epoch = int(time.time())

    commit_data = serialize_commit(root_tree_sha, amend_parents, author, committer, epoch, args.message)
    commit_sha = hash_object(commit_data, "commit", repo.root)

    head = repo.get_head()
    if head.startswith("ref: "):
        ref_path = head.split("ref: ")[1].strip()
        old_sha = repo.get_ref(ref_path) if (repo.root / ".pygit" / ref_path).exists() else "0" * 64
        repo.set_ref(ref_path, commit_sha)
        repo.append_reflog(old_sha, commit_sha, "commit")
    else:
        repo.set_head_detached(commit_sha)
        repo.append_reflog(head, commit_sha, "commit")

    head_for_output = repo.get_head()
    if head_for_output.startswith("ref: "):
        ref_path_out = head_for_output.split("ref: ")[1].strip()
        branch_name = ref_path_out.split("/")[-1]
    else:
        branch_name = commit_sha[:7]

    if amend_parents:
        print(f"[{branch_name} {commit_sha[:7]}] {args.message}")
    else:
        print(f"[{branch_name} (root-commit) {commit_sha[:7]}] {args.message}")


def cmd_log(args):
    """Walk parent chain from HEAD, print commit info."""
    repo = Repository(".")
    use_color = should_color(getattr(args, "color", None))

    try:
        head = repo.get_head()
        if head.startswith("ref: "):
            ref_path = head.split("ref: ")[1].strip()
            sha = repo.get_ref(ref_path)
        else:
            sha = head.strip()
    except (FileNotFoundError, ValueError):
        print("No commits yet", file=sys.stderr)
        return

    if args.path:
        commit_iter = commits_that_touched_path(repo, sha, args.path)
    else:
        commit_iter = walk_commits(repo, sha, count=None if args.author else args.count)

    shown = 0
    for commit_sha, commit in commit_iter:
        if args.author and args.author.lower() not in commit["author"].lower():
            continue
        if args.oneline:
            short = commit_sha[:7]
            msg = commit["message"].splitlines()[0]
            if use_color:
                print(f"{colorize(short, YELLOW)} {msg}")
            else:
                print(f"{short} {msg}")
        else:
            if use_color:
                print(f"commit {colorize(commit_sha, YELLOW)}")
            else:
                print(f"commit {commit_sha}")
            if len(commit["parents"]) > 1:
                print(f"Merge: {' '.join(p[:7] for p in commit['parents'])}")
            print(f"Author: {commit['author']}")
            dt = datetime.datetime.fromtimestamp(commit["committer_epoch"])
            print(f"Date:   {dt.strftime('%a %b %d %H:%M:%S %Y %z')}")
            print(f"\n    {commit['message']}\n")
        shown += 1
        if args.count is not None and shown >= args.count:
            break


def cmd_show(args):
    """Show commit metadata and diff."""
    repo = Repository(".")
    use_color = should_color(getattr(args, "color", None))

    sha = _resolve_ref(repo, args.sha)

    try:
        obj_type, data = read_object(sha, repo.root)
    except Exception:
        print(f"error: unknown revision '{sha}'", file=sys.stderr)
        sys.exit(1)

    if obj_type != "commit":
        print(f"error: {sha} is not a commit", file=sys.stderr)
        sys.exit(1)

    commit = deserialize_commit(data)
    print(f"commit {sha}")
    print(f"Author: {commit['author']}")
    dt = datetime.datetime.fromtimestamp(commit["committer_epoch"])
    print(f"Date:   {dt.strftime('%a %b %d %H:%M:%S %Y %z')}")
    print(f"\n    {commit['message']}\n")

    if commit["parents"]:
        parent_sha = commit["parents"][0]
        try:
            _, parent_data = read_object(parent_sha, repo.root)
            parent_commit = deserialize_commit(parent_data)
            parent_tree = parent_commit["tree"]
        except Exception:
            parent_tree = None
    else:
        parent_tree = None

    def get_tree_files(tree_sha):
        if not tree_sha:
            return {}
        try:
            return {e["path"]: e for e in repo.get_tree_entries_from_tree(tree_sha)}
        except Exception:
            return {}

    parent_files = get_tree_files(parent_tree)
    commit_files = get_tree_files(commit["tree"])

    all_paths = sorted(set(parent_files.keys()) | set(commit_files.keys()))

    for path in all_paths:
        old_entry = parent_files.get(path)
        new_entry = commit_files.get(path)

        old_content = b""
        new_content = b""

        if old_entry:
            _, old_content = read_object(old_entry["sha"], repo.root)
        if new_entry:
            _, new_content = read_object(new_entry["sha"], repo.root)

        old_lines = old_content.decode("utf-8", errors="replace").splitlines(keepends=True)
        new_lines = new_content.decode("utf-8", errors="replace").splitlines(keepends=True)

        diff = list(difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{path}"))
        if diff:
            for line in diff:
                sys.stdout.write(colorize_diff_line(line, use_color))


def cmd_status(args):
    """Diff working tree vs index vs HEAD tree."""
    repo = Repository(".")
    use_color = should_color(getattr(args, "color", None))
    index = Index(repo)
    index.load()

    head_entries = {}
    try:
        head = repo.get_head()
        if head.startswith("ref: "):
            ref_path = head.split("ref: ")[1].strip()
            head_sha = repo.get_ref(ref_path)
        else:
            head_sha = head.strip()
        head_tree = repo.get_tree_entries(head_sha)
        head_entries = {e["path"]: e for e in head_tree}
    except Exception:
        pass

    index_entries = {e["path"]: e for e in index.get_entries()}
    working_files = repo.get_working_tree_files()

    staged = []
    modified = []
    untracked = []

    for path in sorted(index_entries):
        ie = index_entries[path]
        full = repo.root / path
        if path not in working_files:
            modified.append(f"\tdeleted:   {path}")
        elif ie["sha"] != head_entries.get(path, {}).get("sha"):
            staged.append(f"\tnew file:   {path}")
        else:
            current_sha = None
            try:
                current_sha = hash_object(full.read_bytes(), "blob", repo.root)
            except Exception:
                pass
            if current_sha and current_sha != ie["sha"]:
                modified.append(f"\tmodified:   {path}")

    for path in sorted(head_entries):
        if path not in index_entries and path in working_files:
            modified.append(f"\tmodified:   {path}")

    for path in sorted(working_files):
        if path not in index_entries and path not in head_entries:
            untracked.append(f"\t{path}")

    if staged:
        print("Changes to be committed:")
        print("  (use \"git rm --cached <file>...\" to unstage)")
        for s in staged:
            print(colorize_status_item(s, "staged", use_color))
        print()

    if modified:
        print("Changes not staged for commit:")
        print("  (use \"git add <file>...\" to update what will be committed)")
        for m in modified:
            print(colorize_status_item(m, "modified", use_color))
        print()

    if untracked:
        print("Untracked files:")
        print("  (use \"git add <file>...\" to include in what will be committed)")
        for u in untracked:
            print(colorize_status_item(u, "untracked", use_color))
        print()

    if not staged and not modified and not untracked:
        print("nothing to commit, working tree clean")


def _compute_stat(diff_lines):
    """Compute per-file insertions/deletions from unified diff lines."""
    file_stats = []
    current_file = None
    ins = del_ = 0
    for line in diff_lines:
        if line.startswith("--- a/"):
            continue
        elif line.startswith("+++ b/"):
            if current_file:
                file_stats.append((current_file, ins, del_))
            current_file = line[6:]
            ins = del_ = 0
        elif line.startswith("+"):
            ins += 1
        elif line.startswith("-"):
            del_ += 1
    if current_file:
        file_stats.append((current_file, ins, del_))
    total_ins = sum(s[1] for s in file_stats)
    total_del = sum(s[2] for s in file_stats)
    return file_stats, total_ins, total_del


def _print_stat(file_stats, total_ins, total_del):
    """Print diff --stat summary."""
    max_name = max((len(s[0]) for s in file_stats), default=0)
    for name, ins, del_ in file_stats:
        bar = "+" * ins + "-" * del_
        print(f" {name:>{max_name}} | {len(bar):>3} {bar}")
    print(f" {len(file_stats)} file{'s' if len(file_stats) != 1 else ''} changed, "
          f"{total_ins} insertion{'s' if total_ins != 1 else ''}(+), "
          f"{total_del} deletion{'s' if total_del != 1 else ''}(-)")


def cmd_diff(args):
    """Show diff between working tree and index, or index and HEAD, or two commits."""
    repo = Repository(".")
    use_color = should_color(getattr(args, "color", None))

    if args.commits and len(args.commits) == 2:
        try:
            sha1 = resolve_commit_ref(repo, args.commits[0])
            sha2 = resolve_commit_ref(repo, args.commits[1])
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(1)
        diff_lines = diff_two_commits(repo, sha1, sha2)
        if getattr(args, "stat", False):
            file_stats, total_ins, total_del = _compute_stat(diff_lines)
            _print_stat(file_stats, total_ins, total_del)
        else:
            for line in diff_lines:
                sys.stdout.write(colorize_diff_line(line, use_color))
        return
    index = Index(repo)
    index.load()

    if args.commits and len(args.commits) == 1:
        try:
            resolve_commit_ref(repo, args.commits[0])
            print("error: diff requires two commits to compare", file=sys.stderr)
            sys.exit(1)
        except ValueError:
            paths = args.commits
    elif args.commits and len(args.commits) > 2:
        print("error: diff takes 0, 1, or 2 commit arguments", file=sys.stderr)
        sys.exit(1)
    else:
        paths = args.commits if args.commits else [e["path"] for e in index.get_entries()]

    all_diff = []
    for path in paths:
        ie = index.get_entry(path)
        if not ie:
            continue
        full = repo.root / path
        if not full.exists():
            continue
        working = full.read_bytes().decode("utf-8", errors="replace").splitlines(keepends=True)

        if args.staged:
            try:
                head_sha = repo.get_head()
                if head_sha.startswith("ref: "):
                    ref_path = head_sha.split("ref: ")[1].strip()
                    head_sha = repo.get_ref(ref_path)
                head_content = repo.get_file_from_commit(head_sha, path)
                staged = head_content.decode("utf-8", errors="replace").splitlines(keepends=True)
            except Exception:
                staged = []
            diff = difflib.unified_diff(staged, working, fromfile=f"a/{path}", tofile=f"b/{path}")
        else:
            try:
                _, idx_data = read_object(ie["sha"], repo.root)
                idx_lines = idx_data.decode("utf-8", errors="replace").splitlines(keepends=True)
            except Exception:
                idx_lines = []
            diff = difflib.unified_diff(idx_lines, working, fromfile=f"a/{path}", tofile=f"b/{path}")

        all_diff.extend(diff)

    if getattr(args, "stat", False):
        file_stats, total_ins, total_del = _compute_stat(all_diff)
        _print_stat(file_stats, total_ins, total_del)
    else:
        for line in all_diff:
            sys.stdout.write(colorize_diff_line(line, use_color))


def cmd_branch(args):
    """Create, list, or delete branches."""
    repo = Repository(".")
    use_color = should_color(getattr(args, "color", None))

    if args.delete or args.force_delete:
        branch_name = args.name
        if not branch_name:
            print("error: branch name required", file=sys.stderr)
            sys.exit(1)

        ref_path = f"refs/heads/{branch_name}"
        try:
            branch_sha = repo.get_ref(ref_path)
        except FileNotFoundError:
            print(f"error: branch '{branch_name}' not found", file=sys.stderr)
            sys.exit(1)

        head = repo.get_head()
        if head.startswith("ref: "):
            current_ref = head.split("ref: ")[1].strip()
            if current_ref == ref_path:
                print(f"error: Cannot delete checked out branch '{branch_name}'", file=sys.stderr)
                sys.exit(1)

        if not args.force_delete:
            reachable_from_others = set()
            heads_dir = repo.root / ".pygit" / "refs" / "heads"
            if heads_dir.exists():
                for p in heads_dir.iterdir():
                    if p.is_file() and p.name != branch_name:
                        other_sha = repo.get_ref(f"refs/heads/{p.name}")
                        reachable_from_others |= find_reachable(repo, other_sha)

            if branch_sha not in reachable_from_others:
                print(f"error: The branch '{branch_name}' is not fully merged.", file=sys.stderr)
                print(f"error: Use -D to force deletion.", file=sys.stderr)
                sys.exit(1)

        ref_file = repo.root / ".pygit" / ref_path
        ref_file.unlink()
        print(f"Deleted branch {branch_name} (was {branch_sha[:7]})")
    elif args.name:
        head = repo.get_head()
        if head.startswith("ref: "):
            ref_path = head.split("ref: ")[1].strip()
            sha = repo.get_ref(ref_path)
        else:
            sha = head.strip()
        repo.set_ref(f"refs/heads/{args.name}", sha)
        print(f"Branch '{args.name}' created")
    else:
        heads_dir = repo.root / ".pygit" / "refs" / "heads"
        if not heads_dir.exists():
            return
        current = None
        try:
            head = repo.get_head()
            if head.startswith("ref: "):
                current = head.split("ref: ")[1].strip().split("/")[-1]
        except Exception:
            pass
        for name in sorted(p.name for p in heads_dir.iterdir() if p.is_file()):
            if name == current:
                prefix = "* "
                display = colorize(f"{prefix}{name}", GREEN) if use_color else f"{prefix}{name}"
            else:
                prefix = "  "
                display = f"{prefix}{name}"
            print(display)


def cmd_clean(args):
    """Remove untracked files from the working tree."""
    repo = Repository(".")

    if not args.dry_run and not args.force:
        print("error: clean requires -n or -f", file=sys.stderr)
        sys.exit(1)

    clean_repo(
        repo,
        dry_run=args.dry_run,
        include_ignored=args.exclude,
        include_dirs=args.dirs,
    )


def cmd_checkout(args):
    """Move HEAD, rewrite working tree, or restore files."""
    repo = Repository(".")

    if args.new_branch or args.new_branch_force:
        branch_name = args.new_branch or args.new_branch_force
        force = args.new_branch_force is not None
        if not _switch_branch(repo, branch_name, force):
            sys.exit(1)
        args.target = branch_name
    elif args.paths:
        _checkout_paths(repo, args.paths)
        return
    elif not args.target:
        print("error: branch or path required", file=sys.stderr)
        sys.exit(1)

    target = args.target

    ref_path = f"refs/heads/{target}"
    is_branch = False
    try:
        repo.get_ref(ref_path)
        is_branch = True
    except FileNotFoundError:
        pass

    if not is_branch:
        index = None
        try:
            index = Index(repo)
            index.load()
        except Exception:
            pass
        ie = index.get_entry(target) if index else None
        if ie or (repo.root / target).exists():
            _checkout_paths(repo, [target])
            return

    index_entries = {}
    try:
        index = Index(repo)
        index.load()
        index_entries = {e["path"]: e for e in index.get_entries()}
    except Exception:
        pass

    working_files = repo.get_working_tree_files()
    for path in working_files:
        ie = index_entries.get(path)
        if ie:
            try:
                full = repo.root / path
                current_sha = hash_object(full.read_bytes(), "blob", repo.root)
                if current_sha != ie["sha"]:
                    print(f"error: Your local changes to '{path}' would be overwritten", file=sys.stderr)
                    print("Commit your changes or stash them before you switch branches.", file=sys.stderr)
                    sys.exit(1)
            except Exception:
                pass

    is_sha_target = False
    if all(c in "0123456789abcdef" for c in target.lower()):
        try:
            commit_sha = repo.resolve_sha_prefix(target)
            is_sha_target = True
        except ValueError:
            pass

    if not is_sha_target:
        ref_path = f"refs/heads/{target}"
        try:
            commit_sha = repo.get_ref(ref_path)
        except FileNotFoundError:
            print(f"error: pathspec '{target}' did not match any branch", file=sys.stderr)
            sys.exit(1)

    obj_type, data = read_object(commit_sha, repo.root)
    if obj_type != "commit":
        print(f"error: {target} is not a commit", file=sys.stderr)
        sys.exit(1)

    commit = deserialize_commit(data)
    tree_sha = commit["tree"]

    target_entries = repo.get_tree_entries_from_tree(tree_sha)
    target_paths = {e["path"] for e in target_entries}
    index_paths = set(index_entries.keys())
    untracked_on_disk = working_files - index_paths
    collision = untracked_on_disk & target_paths
    if collision:
        for c in sorted(collision):
            print(f"error: untracked working tree file '{c}' would be overwritten by checkout", file=sys.stderr)
        sys.exit(1)

    old_head_raw = repo.get_head()
    if old_head_raw.startswith("ref: "):
        old_ref = old_head_raw.split("ref: ")[1].strip()
        try:
            old_head = repo.get_ref(old_ref)
        except FileNotFoundError:
            old_head = "0" * 64
    else:
        old_head = old_head_raw

    old_tracked = set()
    try:
        old_entries = repo.get_tree_entries(old_head)
        old_tracked = {e["path"] for e in old_entries}
    except Exception:
        pass

    if is_sha_target:
        repo.set_head_detached(commit_sha)
        repo.append_reflog(old_head, commit_sha, "checkout")
    else:
        repo.set_head(f"ref: refs/heads/{target}")
        repo.append_reflog(old_head, commit_sha, "checkout")

    repo.checkout_tree(tree_sha, old_tracked=old_tracked)
    print(f"Switched to branch '{target}'" if not is_sha_target else f"HEAD is now at {commit_sha[:7]}")


def _checkout_paths(repo, paths):
    """Restore specific files from the index."""
    index = Index(repo)
    index.load()

    for path in paths:
        ie = index.get_entry(path)
        if not ie:
            print(f"error: pathspec '{path}' did not match any file known to index", file=sys.stderr)
            sys.exit(1)
        full = repo.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        _, content = read_object(ie["sha"], repo.root)
        full.write_bytes(content)


def cmd_merge(args):
    """Three-way merge."""
    repo = Repository(".")
    try:
        merge_branch(repo, args.branch)
    except Exception as e:
        print(f"merge: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_tag(args):
    """Create lightweight or annotated tag."""
    repo = Repository(".")

    head = repo.get_head()
    if head.startswith("ref: "):
        ref_path = head.split("ref: ")[1].strip()
        commit_sha = repo.get_ref(ref_path)
    else:
        commit_sha = head.strip()

    if args.message:
        tagger = repo.get_author_string()
        epoch = int(time.time())
        tag_data = serialize_tag(commit_sha, "commit", tagger, args.name, epoch, args.message)
        tag_sha = hash_object(tag_data, "tag", repo.root)
        repo.set_ref(f"refs/tags/{args.name}", tag_sha)
    else:
        repo.set_ref(f"refs/tags/{args.name}", commit_sha)

    print(f"Tag '{args.name}' created")


def cmd_reset(args):
    """Move current branch ref to commit."""
    repo = Repository(".")

    commit_sha = _resolve_ref(repo, args.commit)

    head = repo.get_head()
    if not head.startswith("ref: "):
        print("error: HEAD is detached, cannot reset", file=sys.stderr)
        sys.exit(1)

    ref_path = head.split("ref: ")[1].strip()
    old_sha = repo.get_ref(ref_path)

    if args.mode == "soft":
        repo.set_ref(ref_path, commit_sha)
        repo.append_reflog(old_sha, commit_sha, "reset")
    elif args.mode == "mixed" or args.mode is None:
        repo.set_ref(ref_path, commit_sha)
        repo.append_reflog(old_sha, commit_sha, "reset")
        index = Index(repo)
        commit_obj_type, data = read_object(commit_sha, repo.root)
        commit = deserialize_commit(data)
        tree_entries = repo.get_tree_entries_from_tree(commit["tree"])
        index.clear()
        for entry in tree_entries:
            index.add(entry["path"], entry["sha"], entry["mode"], 0)
        index.save()
    elif args.mode == "hard":
        repo.set_ref(ref_path, commit_sha)
        repo.append_reflog(old_sha, commit_sha, "reset")
        index = Index(repo)
        commit_obj_type, data = read_object(commit_sha, repo.root)
        commit = deserialize_commit(data)
        repo.checkout_tree(commit["tree"])
        tree_entries = repo.get_tree_entries_from_tree(commit["tree"])
        index.clear()
        for entry in tree_entries:
            index.add(entry["path"], entry["sha"], entry["mode"], 0)
        index.save()

    print(f"HEAD is now at {commit_sha[:7]}")


def cmd_stash(args):
    """Save or restore working state."""
    repo = Repository(".")

    if args.stash_action == "push" or args.stash_action is None:
        stash_push(repo)
        print("Saved working directory and index state")
    elif args.stash_action == "pop":
        stash_pop(repo)
        print("stash: On top of HEAD")
    elif args.stash_action == "list":
        stash_list(repo)


def cmd_cherry_pick(args):
    """Apply a commit's changes to current branch."""
    repo = Repository(".")
    sha = _resolve_ref(repo, args.sha)
    try:
        cherry_pick(repo, sha)
    except Exception as e:
        print(f"cherry-pick: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_rebase(args):
    """Replay current branch commits on top of another branch."""
    repo = Repository(".")
    try:
        rebase(repo, args.branch)
    except Exception as e:
        print(f"rebase: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_reflog(args):
    """Print HEAD movement history."""
    repo = Repository(".")
    reflog_path = repo.root / ".pygit" / "logs" / "HEAD"
    if not reflog_path.exists():
        return
    print(reflog_path.read_text())


def cmd_remote(args):
    """Manage remotes."""
    repo = Repository(".")
    action = args.remote_action
    if action is None:
        action = "list"
    if action == "add":
        repo.add_remote(args.name, args.address)
        print(f"Remote '{args.name}' added")
    elif action == "list":
        config = repo.get_config()
        verbose = getattr(args, "verbose", False)
        found = False
        for section in config.sections():
            if section.startswith("remote "):
                name = section.split('"')[1]
                addr = config.get(section, "address")
                if verbose:
                    print(f"{name}\t{addr}")
                else:
                    print(name)
                found = True
        if not found:
            print("No remotes configured")


def cmd_fetch(args):
    """Fetch from remote."""
    repo = Repository(".")
    address = repo.get_remote(args.remote)
    host, port = address.split(":")
    client = Client(repo)
    client.fetch(args.remote, host, int(port))
    print(f"Fetched from {args.remote}")


def cmd_blame(args):
    """Per-line commit attribution."""
    repo = Repository(".")
    blame(repo, args.path)


def cmd_revert(args):
    """Create a commit that undoes a previous commit."""
    repo = Repository(".")
    sha = _resolve_ref(repo, args.sha)
    try:
        revert(repo, sha)
    except Exception as e:
        print(f"revert: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_gc(args):
    """Pack loose objects, delete unreachable objects."""
    repo = Repository(".")
    gc(repo)
    print("Garbage collection complete")


def cmd_serve(args):
    repo = Repository(".")
    server = Server(repo, args.bind, args.port)
    print(f"Serving on {args.bind}:{args.port}")
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nServer stopped.")


def cmd_clone(args):
    """Clone from a remote server."""
    host, port = args.host_port.split(":")
    repo = Repository(args.dir)
    repo.init()
    client = Client(repo)
    client.clone(host, int(port))
    print(f"Cloned into '{args.dir}'")


def cmd_push(args):
    """Push to a remote server."""
    repo = Repository(".")
    client = Client(repo)
    host, port = args.host_port.split(":")
    try:
        client.push(host, int(port))
        print(f"Pushed to {args.host_port}")
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def cmd_switch(args):
    """Switch to a branch (modern alternative to checkout)."""
    repo = Repository(".")

    if args.new_branch or args.new_branch_force:
        branch_name = args.new_branch or args.new_branch_force
        force = args.new_branch_force is not None
        if not _switch_branch(repo, branch_name, force):
            sys.exit(1)
        target = branch_name
    elif args.target:
        target = args.target
        if all(c in "0123456789abcdef" for c in target.lower()):
            try:
                repo.resolve_sha_prefix(target)
                print(f"fatal: cannot switch to a commit", file=sys.stderr)
                sys.exit(1)
            except ValueError:
                pass
        ref_path = f"refs/heads/{target}"
        try:
            repo.get_ref(ref_path)
        except FileNotFoundError:
            print(f"error: pathspec '{target}' did not match any branch", file=sys.stderr)
            sys.exit(1)
    else:
        print("error: branch required", file=sys.stderr)
        sys.exit(1)

    cmd_args = argparse.Namespace(target=target, new_branch=None, new_branch_force=None, paths=None)
    cmd_checkout(cmd_args)


def cmd_config(args):
    """Get or set repository configuration."""
    repo = Repository(".")

    if args.value is not None:
        repo.set_config_value(args.key, args.value)
    else:
        config = repo.get_config()
        parts = args.key.split(".")
        if len(parts) == 2:
            section, option = parts
            try:
                print(config.get(section, option))
            except Exception:
                print(f"error: key '{args.key}' not found", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"error: key must be in section.option format (e.g. user.name)", file=sys.stderr)
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="pygit",
        description="pygit — a real, content-addressed version control system in pure Python",
    )
    subparsers = parser.add_subparsers(dest="command", help="available commands")

    p_init = subparsers.add_parser("init", help="create an empty pygit repository")
    p_init.add_argument("path", nargs="?", default=".", help="repository path")
    p_init.set_defaults(func=cmd_init)

    p_add = subparsers.add_parser("add", help="add file contents to the index")
    p_add.add_argument("paths", nargs="+", help="files to add")
    p_add.set_defaults(func=cmd_add)

    p_commit = subparsers.add_parser("commit", help="record changes to the repository")
    p_commit.add_argument("-m", "--message", help="commit message")
    p_commit.add_argument("--amend", action="store_true", help="amend the last commit")
    p_commit.set_defaults(func=cmd_commit)

    p_log = subparsers.add_parser("log", help="show commit logs")
    p_log.add_argument("--oneline", action="store_true", help="show one line per commit")
    p_log.add_argument("-n", "--count", type=int, default=None, help="limit number of commits")
    p_log.add_argument("--author", default=None, help="filter by author (substring match)")
    p_log.add_argument("path", nargs="?", default=None, help="only show commits that changed this path")
    p_log.add_argument("--color", choices=["always", "never", "auto"], default="auto", help="color output")
    p_log.set_defaults(func=cmd_log)

    p_show = subparsers.add_parser("show", help="show commit metadata and diff")
    p_show.add_argument("sha", help="commit sha")
    p_show.add_argument("--color", choices=["always", "never", "auto"], default="auto", help="color output")
    p_show.set_defaults(func=cmd_show)

    p_status = subparsers.add_parser("status", help="show the working tree status")
    p_status.add_argument("--color", choices=["always", "never", "auto"], default="auto", help="color output")
    p_status.set_defaults(func=cmd_status)

    p_diff = subparsers.add_parser("diff", help="show changes between commits, working tree, and index")
    p_diff.add_argument("commits", nargs="*", help="commit references to diff (exactly 2 for commit-to-commit)")
    p_diff.add_argument("--staged", action="store_true", help="show staged changes")
    p_diff.add_argument("--stat", action="store_true", help="show summary instead of full diff")
    p_diff.add_argument("--color", choices=["always", "never", "auto"], default="auto", help="color output")
    p_diff.set_defaults(func=cmd_diff)

    p_branch = subparsers.add_parser("branch", help="list, create, or delete branches")
    p_branch.add_argument("name", nargs="?", help="branch name")
    p_branch.add_argument("-d", "--delete", action="store_true", help="delete a fully merged branch")
    p_branch.add_argument("-D", "--force-delete", action="store_true", help="force delete a branch")
    p_branch.add_argument("--color", choices=["always", "never", "auto"], default="auto", help="color output")
    p_branch.set_defaults(func=cmd_branch)

    p_checkout = subparsers.add_parser("checkout", help="switch branches or restore working tree")
    checkout_bg = p_checkout.add_mutually_exclusive_group()
    checkout_bg.add_argument("-b", dest="new_branch", metavar="NAME", help="create new branch")
    checkout_bg.add_argument("-B", dest="new_branch_force", metavar="NAME", help="create or reset branch")
    p_checkout.add_argument("target", nargs="?", help="branch name or commit sha")
    p_checkout.add_argument("paths", nargs="*", metavar="path", help="files to restore from index")
    p_checkout.set_defaults(func=cmd_checkout)

    p_clean = subparsers.add_parser("clean", help="remove untracked files from the working tree")
    p_clean.add_argument("-n", "--dry-run", action="store_true", help="dry run (show what would be removed)")
    p_clean.add_argument("-f", "--force", action="store_true", help="actually remove files")
    p_clean.add_argument("-d", "--dirs", action="store_true", help="also remove untracked directories")
    p_clean.add_argument("-x", "--exclude", action="store_true", help="also remove ignored files")
    p_clean.set_defaults(func=cmd_clean)

    p_merge = subparsers.add_parser("merge", help="join two or more development histories")
    p_merge.add_argument("branch", help="branch to merge")
    p_merge.set_defaults(func=cmd_merge)

    p_tag = subparsers.add_parser("tag", help="create, list, delete or verify a tag")
    p_tag.add_argument("name", help="tag name")
    p_tag.add_argument("-m", "--message", help="tag message (creates annotated tag)")
    p_tag.set_defaults(func=cmd_tag)

    p_reset = subparsers.add_parser("reset", help="reset current HEAD to specified state")
    p_reset.add_argument("--soft", action="store_const", const="soft", dest="mode", help="soft reset")
    p_reset.add_argument("--mixed", action="store_const", const="mixed", dest="mode", help="mixed reset")
    p_reset.add_argument("--hard", action="store_const", const="hard", dest="mode", help="hard reset")
    p_reset.add_argument("commit", help="target commit")
    p_reset.set_defaults(func=cmd_reset)

    p_stash = subparsers.add_parser("stash", help="stash away changes")
    p_stash.add_argument("stash_action", nargs="?", default="push", choices=["push", "pop", "list"],
                         help="stash action")
    p_stash.set_defaults(func=cmd_stash)

    p_cherrypick = subparsers.add_parser("cherry-pick", help="apply a commit's changes")
    p_cherrypick.add_argument("sha", help="commit sha to cherry-pick")
    p_cherrypick.set_defaults(func=cmd_cherry_pick)

    p_rebase = subparsers.add_parser("rebase", help="reapply commits on top of another base")
    p_rebase.add_argument("branch", help="branch to rebase onto")
    p_rebase.set_defaults(func=cmd_rebase)

    p_reflog = subparsers.add_parser("reflog", help="show reflog")
    p_reflog.set_defaults(func=cmd_reflog)

    p_remote = subparsers.add_parser("remote", help="manage remote repositories")
    p_remote.add_argument("-v", "--verbose", action="store_true", help="show remote URLs")
    remote_sub = p_remote.add_subparsers(dest="remote_action", help="remote actions")
    p_remote_add = remote_sub.add_parser("add", help="add a remote")
    p_remote_add.add_argument("name", help="remote name")
    p_remote_add.add_argument("address", help="host:port")
    remote_sub.add_parser("list", help="list configured remotes")
    p_remote.set_defaults(func=cmd_remote)

    p_fetch = subparsers.add_parser("fetch", help="download objects and refs from a remote")
    p_fetch.add_argument("remote", help="remote name")
    p_fetch.set_defaults(func=cmd_fetch)

    p_blame = subparsers.add_parser("blame", help="show what revision and author last modified each line")
    p_blame.add_argument("path", help="file path")
    p_blame.set_defaults(func=cmd_blame)

    p_revert = subparsers.add_parser("revert", help="revert an existing commit")
    p_revert.add_argument("sha", help="commit sha to revert")
    p_revert.set_defaults(func=cmd_revert)

    p_gc = subparsers.add_parser("gc", help="clean up unnecessary files and optimize the repository")
    p_gc.set_defaults(func=cmd_gc)

    p_clone = subparsers.add_parser("clone", help="clone a remote repository")
    p_clone.add_argument("host_port", help="host:port of the server")
    p_clone.add_argument("dir", help="target directory")
    p_clone.set_defaults(func=cmd_clone)

    p_push = subparsers.add_parser("push", help="update remote refs along with associated objects")
    p_push.add_argument("host_port", help="host:port of the server")
    p_push.set_defaults(func=cmd_push)

    p_serve = subparsers.add_parser("serve", help="start a server to serve this repository")
    p_serve.add_argument("--port", type=int, default=9418, help="port to listen on (default: 9418)")
    p_serve.add_argument("--bind", default="0.0.0.0", help="address to bind to (default: 0.0.0.0)")
    p_serve.set_defaults(func=cmd_serve)

    p_switch = subparsers.add_parser("switch", help="switch to a branch (modern alternative to checkout)")
    switch_bg = p_switch.add_mutually_exclusive_group()
    switch_bg.add_argument("-c", dest="new_branch", metavar="NAME", help="create new branch and switch")
    switch_bg.add_argument("-C", dest="new_branch_force", metavar="NAME", help="create or reset branch and switch")
    p_switch.add_argument("target", nargs="?", help="branch name")
    p_switch.set_defaults(func=cmd_switch)

    p_config = subparsers.add_parser("config", help="get or set repository configuration")
    p_config.add_argument("key", help="config key (e.g. user.name)")
    p_config.add_argument("value", nargs="?", help="value to set (omit to read)")
    p_config.set_defaults(func=cmd_config)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
