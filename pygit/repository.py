"""Repository management for pygit.

Handles .pygit/ structure, HEAD, refs, config, and working tree operations.
"""

import configparser
import os
import time
import shutil
from pathlib import Path

from .objects import (
    hash_object, read_object, deserialize_tree, deserialize_commit,
    serialize_tree
)


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

        # HEAD
        head_file = self.git_dir / "HEAD"
        if not head_file.exists():
            head_file.write_text("ref: refs/heads/main\n")

        # config
        config_file = self.git_dir / "config"
        if not config_file.exists():
            config = configparser.ConfigParser()
            with config_file.open("w") as f:
                config.write(f)

        # index
        index_file = self.git_dir / "index"
        if not index_file.exists():
            index_file.write_text("[]")

        # stash
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
        """Resolve an abbreviated sha prefix to a full sha.

        Args:
            prefix: 4-64 character hex string (sha prefix)

        Returns:
            Full 64-character sha string

        Raises:
            ValueError: if prefix is too short, matches nothing, or is ambiguous
        """
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
                    import json
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
            # Skip .pygit directory
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
        """Build tree objects bottom-up from index entries.

        Returns:
            SHA of the root tree
        """
        entries = index.get_entries()
        if not entries:
            # Empty tree
            tree_data = serialize_tree([])
            return hash_object(tree_data, "tree", self.root)

        # Group entries by directory
        tree_map = {}  # dir_path -> [(mode, name, sha)]

        for entry in entries:
            path = entry["path"]
            parts = Path(path).parts

            if len(parts) == 1:
                # File in root
                tree_map.setdefault("", []).append(
                    (entry["mode"], parts[0], entry["sha"])
                )
            else:
                # File in subdirectory
                dir_path = str(Path(*parts[:-1]))
                tree_map.setdefault(dir_path, []).append(
                    (entry["mode"], parts[-1], entry["sha"])
                )

        # Build trees bottom-up
        dir_shas = {}
        for dir_path in sorted(tree_map.keys(), reverse=True):
            entries_for_tree = list(tree_map[dir_path])

            # Add subtree entries
            for child_dir in list(dir_shas.keys()):
                if child_dir.startswith(dir_path + "/") or (
                    dir_path == "" and "/" in child_dir
                ):
                    child_name = child_dir.split("/")[-1] if "/" in child_dir else child_dir
                    entries_for_tree.append(("40000", child_name, dir_shas[child_dir]))

            tree_data = serialize_tree(entries_for_tree)
            dir_shas[dir_path] = hash_object(tree_data, "tree", self.root)

        # Root tree
        root_entries = list(tree_map.get("", []))
        for child_dir, child_sha in dir_shas.items():
            if child_dir and "/" not in child_dir:  # Direct child, skip root
                root_entries.append(("40000", child_dir, child_sha))

        root_tree_data = serialize_tree(root_entries)
        return hash_object(root_tree_data, "tree", self.root)

    def get_tree_entries(self, commit_sha):
        """Get all file entries reachable from a commit's tree.

        Returns:
            List of dicts with 'path', 'sha', 'mode' keys
        """
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
                # Subtree - recurse
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

        from .index import Index
        index = Index(self)
        index.clear()
        for entry in entries:
            index.add(entry["path"], entry["sha"], entry["mode"], 0)
        index.save()
