import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.run_local import ROOT, launch


class DistributedAllreduceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        if not compiler or shutil.which(compiler[0]) is None:
            raise unittest.SkipTest("a C++17 compiler is not installed")
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.tempdir.name) / "ring_allreduce"
        source = ROOT / "src" / "ring_allreduce.cpp"
        subprocess.run(compiler + ["-std=c++17", "-O2", "-Wall", "-Wextra",
                                   "-Wpedantic", "-Werror", "-pthread",
                                   str(source), "-o", str(cls.binary)],
                       cwd=ROOT, check=True)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tempdir"):
            cls.tempdir.cleanup()

    def run_cluster_or_skip(self, world_size, elements):
        try:
            return launch(self.binary, world_size, elements, timeout=25)
        except PermissionError as exc:
            raise unittest.SkipTest(f"the current environment blocks loopback sockets: {exc}")
        except RuntimeError as exc:
            if "port block" in str(exc):
                raise unittest.SkipTest(str(exc))
            raise

    def assert_all_ranks_have_sum(self, world_size, elements):
        results, wall_seconds = self.run_cluster_or_skip(world_size, elements)
        expected_value = world_size * (world_size + 1) / 2
        self.assertGreaterEqual(wall_seconds, 0)
        self.assertEqual(len(results), world_size)
        for rank, result in enumerate(results):
            with self.subTest(rank=rank):
                self.assertEqual(result["rank"], rank)
                self.assertEqual(result["world_size"], world_size)
                self.assertEqual(result["elements"], elements)
                self.assertEqual(result["first_value"], expected_value)
                self.assertEqual(result["last_value"], expected_value)
                self.assertEqual(result["checksum"], expected_value * elements)
                if world_size > 1:
                    self.assertGreater(result["bytes_sent"], 0)

    def test_uneven_tensor_across_three_ranks(self):
        self.assert_all_ranks_have_sum(world_size=3, elements=11)

    def test_empty_chunks_when_world_is_larger_than_tensor(self):
        self.assert_all_ranks_have_sum(world_size=4, elements=2)

    def test_single_rank_needs_no_network_socket(self):
        result = subprocess.run([str(self.binary), "--rank", "0", "--world-size", "1",
                                 "--elements", "7"], cwd=ROOT, capture_output=True,
                                text=True, check=True)
        record = json.loads(result.stdout)
        self.assertEqual(record["checksum"], 7)
        self.assertEqual(record["bytes_sent"], 0)

    def test_invalid_rank_fails_before_opening_sockets(self):
        result = subprocess.run([str(self.binary), "--rank", "2", "--world-size", "2"],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("rank must be within", result.stderr)


if __name__ == "__main__":
    unittest.main()
