"""Content-addressed object store for pygit.

Implements git's object model: blob, tree, commit, tag.
All objects are sha256-hashed and zlib-compressed.
"""

import hashlib
import zlib
import os
import struct
from pathlib import Path


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
    """Hash data and store it as a zlib-compressed object.

    Args:
        data: Raw bytes content
        obj_type: One of 'blob', 'tree', 'commit', 'tag'
        repo_root: Repository root path (default: cwd)

    Returns:
        Hex SHA-256 digest (64 chars)
    """
    if isinstance(data, str):
        data = data.encode("utf-8")

    # Git object format: "<type> <byte-length>\0<content>"
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
    """Read and decompress an object by its SHA.

    Args:
        sha: 64-character hex SHA digest
        repo_root: Repository root path (default: cwd)

    Returns:
        Tuple of (type_string, raw_content_bytes)

    Raises:
        FileNotFoundError: If object doesn't exist
    """
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
        import json
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
    """Serialize blob data. Blob is just raw content.

    Args:
        data: Raw bytes

    Returns:
        Raw bytes (same as input)
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return data


def deserialize_blob(raw):
    """Deserialize blob data.

    Args:
        raw: Raw bytes from object store

    Returns:
        Tuple of ('blob', raw_bytes)
    """
    return ("blob", raw)


def serialize_tree(entries):
    """Serialize a tree object from entry list.

    Args:
        entries: List of (mode, name, sha) tuples.
                 mode is a string like '100644' or '40000'.
                 sha is a 64-char hex string.

    Returns:
        Serialized tree bytes
    """
    # Sort by name
    sorted_entries = sorted(entries, key=lambda e: e[1])

    parts = []
    for mode, name, sha in sorted_entries:
        if isinstance(name, str):
            name = name.encode("utf-8")
        # Convert hex sha to 32 raw bytes
        raw_sha = bytes.fromhex(sha)
        parts.append(f"{mode} ".encode() + name + b"\0" + raw_sha)

    return b"".join(parts)


def deserialize_tree(raw):
    """Deserialize a tree object.

    Args:
        raw: Raw tree bytes

    Returns:
        List of (mode, name, sha_hex) tuples
    """
    entries = []
    i = 0
    while i < len(raw):
        # Find space (end of mode)
        space_idx = raw.index(b" ", i)
        mode = raw[i:space_idx].decode()

        # Find null (end of name)
        null_idx = raw.index(b"\0", space_idx)
        name = raw[space_idx + 1:null_idx].decode()

        # Next 32 bytes are the raw SHA
        sha_raw = raw[null_idx + 1:null_idx + 33]
        sha_hex = sha_raw.hex()

        entries.append((mode, name, sha_hex))
        i = null_idx + 33

    return entries


def serialize_commit(tree_sha, parents, author, committer, epoch, message):
    """Serialize a commit object.

    Args:
        tree_sha: SHA of the root tree
        parents: List of parent commit SHAs (empty for root commit)
        author: Author string (e.g., "Name <email>")
        committer: Committer string
        epoch: Unix timestamp integer
        message: Commit message

    Returns:
        Serialized commit bytes
    """
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
    """Deserialize a commit object.

    Args:
        raw: Raw commit bytes

    Returns:
        Dict with keys: tree, parents, author, committer, author_epoch,
        committer_epoch, message
    """
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

    # Message is everything after the blank line
    result["message"] = "\n".join(lines[i + 1:]).strip()
    return result


def serialize_tag(object_sha, object_type, tagger, tag_name, epoch, message):
    """Serialize a tag object.

    Args:
        object_sha: SHA of the tagged object
        object_type: Type of the tagged object (e.g., 'commit')
        tagger: Tagger string (e.g., "Name <email>")
        tag_name: Name of the tag
        epoch: Unix timestamp integer
        message: Tag message

    Returns:
        Serialized tag bytes
    """
    lines = []
    lines.append(f"object {object_sha}")
    lines.append(f"type {object_type}")
    lines.append(f"tag {tag_name}")
    lines.append(f"tagger {tagger} {epoch}")
    lines.append("")
    lines.append(message)

    return "\n".join(lines).encode("utf-8")


def deserialize_tag(raw):
    """Deserialize a tag object.

    Args:
        raw: Raw tag bytes

    Returns:
        Dict with keys: object, type, tag, tagger, tagger_epoch, message
    """
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
