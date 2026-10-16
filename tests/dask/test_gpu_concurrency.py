"""Tests for config/dask/sample/gpu_concurrency.py, the Dask GPU sample workload.

The manifest and time-slicing checks are Go tests (internal/lab/config_test.go).
The LocalCluster test needs dask distributed and is skipped without it.
"""

import importlib.util
import time
import unittest
from pathlib import Path

DASK_DIR = Path(__file__).resolve().parents[2] / "config" / "dask"


def load_concurrency_module():
    spec = importlib.util.spec_from_file_location(
        "gpu_concurrency", DASK_DIR / "sample" / "gpu_concurrency.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sleep_task(seconds):
    """CPU stand-in for gpu_task"""
    from distributed import get_worker
    start = time.time()
    time.sleep(seconds)
    return {"worker": get_worker().name, "gpu": "-", "start": start,
            "end": time.time(), "iterations": 1}


class ConcurrencyCheckTests(unittest.TestCase):
    def setUp(self):
        self.module = load_concurrency_module()

    def result(self, worker, start, end):
        return {"worker": worker, "start": start, "end": end}

    def test_overlapping_tasks_pass(self):
        results = [self.result(f"w{i}", i, 10 + i) for i in range(4)]
        ok, message = self.module.check_concurrent(results, 4)
        self.assertTrue(ok, message)

    def test_sequential_tasks_fail(self):
        results = [self.result(f"w{i}", i * 10, i * 10 + 5) for i in range(4)]
        self.assertFalse(self.module.check_concurrent(results, 4)[0])

    def test_tasks_on_too_few_workers_fail(self):
        results = [self.result("w0", 0, 10) for _ in range(4)]
        self.assertFalse(self.module.check_concurrent(results, 4)[0])

    @unittest.skipUnless(importlib.util.find_spec("distributed"), "dask distributed not installed")
    def test_run_places_one_concurrent_task_per_worker(self):
        from distributed import Client, LocalCluster
        with LocalCluster(n_workers=4, threads_per_worker=1, processes=False,
                          dashboard_address=None) as cluster, Client(cluster) as client:
            results = self.module.run(client, 4, sleep_task, 1.0)
        ok, message = self.module.check_concurrent(results, 4)
        self.assertTrue(ok, message)


if __name__ == "__main__":
    unittest.main()
