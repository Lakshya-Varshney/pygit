"""Packfile and garbage collection for pygit.

Implements packfile writer/reader with JSON sidecar index,
and gc command to consolidate loose objects.
"""

import json
import os
import time
import uuid
import zlib
from pathlib import Path

from .objects import read_object, deserialize_commit, deserialize_tree


class PackWriter:
    """Writes objects to a packfile with a JSON sidecar index."""

    def __init__(self, repo):
        self.repo = repo
        self.pack_dir = repo.git_dir / "objects" / "pack"
        self.pack_dir.mkdir(parents=True, exist_ok=True)
        self.objects = []  # (sha, compressed_data)
        self.offsets = {}  # sha -> offset

    def add_object(self, sha):
        """Add an object to the packfile.

        Args:
            sha: Object SHA to add
        """
        if sha in self.offsets:
            return  # Already packed

        try:
            obj_type, data = read_object(sha, self.repo.root)
        except FileNotFoundError:
            return

        # Reconstruct the git object format
        header = f"{obj_type} {len(data)}\0".encode()
        store = header + data
        compressed = zlib.compress(store)

        offset = sum(len(c) for _, c in self.objects)
        self.offsets[sha] = offset
        self.objects.append((sha, compressed))

    def write_pack(self):
        """Write the packfile and JSON sidecar index.

        Returns:
            Path to the packfile
        """
        pack_id = str(uuid.uuid4())[:8]
        pack_path = self.pack_dir / f"pack-{pack_id}.pack"
        index_path = self.pack_dir / f"pack-{pack_id}.json"

        # Write packfile
        with open(pack_path, "wb") as f:
            for sha, compressed in self.objects:
                f.write(compressed)

        # Write JSON sidecar index
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
        """Read an object from packfiles.

        Args:
            sha: Object SHA

        Returns:
            Tuple of (type, data) or None if not found
        """
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
    """Find all objects reachable from refs and reflogs.

    Args:
        repo: Repository instance

    Returns:
        Set of reachable object SHAs
    """
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

    # Walk all refs
    refs_dir = repo.git_dir / "refs"
    if refs_dir.exists():
        for ref_file in refs_dir.rglob("*"):
            if ref_file.is_file():
                try:
                    sha = ref_file.read_text().strip()
                    if len(sha) == 64:
                        # Check if it's a tag object (need to dereference)
                        try:
                            obj_type, _ = read_object(sha, repo.root)
                            if obj_type == "tag":
                                from .objects import deserialize_tag
                                _, tag_data = read_object(sha, repo.root)
                                tag = deserialize_tag(tag_data)
                                walk_commit(tag["object"])
                            else:
                                walk_commit(sha)
                        except Exception:
                            walk_commit(sha)
                except Exception:
                    pass

    # Walk reflogs
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
    """Garbage collection: pack loose objects, delete unreachable.

    Args:
        repo: Repository instance
    """
    # Find all reachable objects
    reachable = find_reachable_objects(repo)

    # Pack reachable objects
    pack_writer = PackWriter(repo)
    for sha in reachable:
        pack_writer.add_object(sha)

    if pack_writer.objects:
        pack_writer.write_pack()

    # Delete loose objects that are now packed
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

    # Delete unreachable loose objects
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
