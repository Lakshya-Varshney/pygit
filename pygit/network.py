"""Network protocol for pygit.

Custom protocol for clone/push/fetch over raw sockets.
Not compatible with git's wire protocol.
"""

import json
import os
import socket
import struct
import sys
import zlib
from pathlib import Path

from .objects import (
    hash_object, read_object, deserialize_commit, deserialize_tree,
    serialize_tree
)
from .repository import Repository
from .merge import find_merge_base


def find_reachable(repo, sha):
    """Walk all objects reachable from sha (commit → tree → blobs/subtrees).

    Returns a set of every object SHA needed to materialize the history
    reachable from the given commit.  Blobs are included even though
    nothing further can be recursed into them — they count as reachable.
    """
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

            from .objects import deserialize_commit
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
