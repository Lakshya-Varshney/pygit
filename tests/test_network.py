"""Tests for network protocol."""

import os
import shutil
import socket
import tempfile
import threading
import time
import unittest

from pygit_single import Repository
from pygit_single import hash_object, serialize_tree, serialize_commit
from pygit_single import Server, Client


class TestNetwork(unittest.TestCase):
    """Test network protocol."""

    def setUp(self):
        self.server_dir = tempfile.mkdtemp()
        self.client_dir = tempfile.mkdtemp()
        self.server_repo = Repository(self.server_dir)
        self.server_repo.init()
        self.server_repo.set_user("Server", "s@s.com")

    def tearDown(self):
        shutil.rmtree(self.server_dir)
        shutil.rmtree(self.client_dir)

    def _create_server_commit(self):
        """Create a commit on the server."""
        content = b"server content"
        blob_sha = hash_object(content, "blob", self.server_repo.root)
        tree_entries = [("100644", "file.txt", blob_sha)]
        tree_data = serialize_tree(tree_entries)
        tree_sha = hash_object(tree_data, "tree", self.server_repo.root)

        commit_data = serialize_commit(
            tree_sha, [], "Server <s@s.com>", "Server <s@s.com>", 1000, "server commit"
        )
        commit_sha = hash_object(commit_data, "commit", self.server_repo.root)
        self.server_repo.set_ref("refs/heads/main", commit_sha)

    def test_server_starts(self):
        """Test that server can be created."""
        server = Server(self.server_repo, port=15000)
        self.assertIsNotNone(server)


if __name__ == "__main__":
    unittest.main()
