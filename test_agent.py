import tempfile
import unittest
from pathlib import Path

from agent import AgentError, ProjectWorkspace


class ProjectWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.confirmed = []
        self.workspace = ProjectWorkspace(self.root, lambda path: self.confirmed.append(path) or True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_write_read_and_edit_file(self):
        self.workspace.write_file("src/example.txt", "hello world")
        self.assertEqual("hello world", self.workspace.read_file("src/example.txt"))
        self.workspace.edit_file("src/example.txt", "world", "agent")
        self.assertEqual("hello agent", self.workspace.read_file("src/example.txt"))
        self.assertIn("src/example.txt", self.workspace.list_files())

    def test_blocks_escape_from_workspace(self):
        with self.assertRaises(AgentError):
            self.workspace.write_file("../outside.txt", "blocked")
        with self.assertRaises(AgentError):
            self.workspace.read_file("/tmp/outside.txt")

    def test_delete_calls_confirmation(self):
        self.workspace.write_file("delete-me.txt", "x")
        self.workspace.delete_path("delete-me.txt")
        self.assertEqual(1, len(self.confirmed))
        self.assertFalse((self.root / "delete-me.txt").exists())

    def test_edit_requires_one_match(self):
        self.workspace.write_file("repeat.txt", "same same")
        with self.assertRaises(AgentError):
            self.workspace.edit_file("repeat.txt", "same", "new")


if __name__ == "__main__":
    unittest.main()
