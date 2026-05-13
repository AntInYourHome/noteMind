"""Tests for ingest_cache, ingest_queue, lint, and cascade_delete modules."""

import json
import os
import tempfile

import pytest

from scripts.ingest_cache import IngestCache, compute_sha256, check_cache_hit
from scripts.ingest_queue import IngestQueue, IngestTask, MAX_RETRIES


# ── ingest_cache tests ─────────────────────────────────────

class TestIngestCache:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_empty_cache(self):
        cache = IngestCache(self.tmpdir)
        assert cache.get("/nonexistent") is None
        assert cache.stats()["total"] == 0

    def test_put_and_get(self):
        cache = IngestCache(self.tmpdir)
        test_path = os.path.join(self.tmpdir, "a.pdf")
        with open(test_path, "w") as f:
            f.write("test")
        cache.put(test_path, "sha1", [os.path.join(self.tmpdir, "out", "a.md")], "cat1", ["tag1", "tag2"])
        entry = cache.get(test_path)
        assert entry is not None
        assert entry["sha256"] == "sha1"
        assert entry["category"] == "cat1"
        assert entry["tags"] == ["tag1", "tag2"]

    def test_cache_hit(self):
        test_file = os.path.join(self.tmpdir, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello")
        sha = compute_sha256(test_file)

        cache = IngestCache(self.tmpdir)
        cache.put(test_file, sha, [os.path.join(self.tmpdir, "out.md")], "cat", ["t"])

        result = check_cache_hit(cache, test_file)
        assert result is not None

    def test_cache_miss_wrong_hash(self):
        test_file = os.path.join(self.tmpdir, "test2.txt")
        with open(test_file, "w") as f:
            f.write("hello")

        cache = IngestCache(self.tmpdir)
        cache.put(test_file, "wrong_sha", [os.path.join(self.tmpdir, "out.md")])

        result = check_cache_hit(cache, test_file)
        assert result is None  # hash 不匹配

    def test_persistence(self):
        test_path = os.path.join(self.tmpdir, "b.pdf")
        with open(test_path, "w") as f:
            f.write("test content")
        cache1 = IngestCache(self.tmpdir)
        cache1.put(test_path, compute_sha256(test_path), [os.path.join(self.tmpdir, "out", "b.md")])

        cache2 = IngestCache(self.tmpdir)
        entry = cache2.get(test_path)
        assert entry is not None

    def test_invalidate(self):
        cache = IngestCache(self.tmpdir)
        test_path = os.path.join(self.tmpdir, "c.pdf")
        with open(test_path, "w") as f:
            f.write("test")
        cache.put(test_path, "sha3", [os.path.join(self.tmpdir, "out", "c.md")])
        assert cache.invalidate(test_path)
        assert cache.get(test_path) is None

    def test_invalidate_all(self):
        cache = IngestCache(self.tmpdir)
        p1 = os.path.join(self.tmpdir, "a.pdf")
        p2 = os.path.join(self.tmpdir, "b.pdf")
        with open(p1, "w") as f:
            f.write("a")
        with open(p2, "w") as f:
            f.write("b")
        cache.put(p1, "sha_a", [])
        cache.put(p2, "sha_b", [])
        count = cache.invalidate_all()
        assert count == 2
        assert cache.stats()["total"] == 0


# ── ingest_queue tests ──────────────────────────────────────

class TestIngestQueue:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_empty_queue(self):
        q = IngestQueue(self.tmpdir)
        assert q.is_empty()
        assert q.get_next_pending() is None

    def test_enqueue_batch(self):
        q = IngestQueue(self.tmpdir)
        p1 = os.path.join(self.tmpdir, "a")
        p2 = os.path.join(self.tmpdir, "b")
        p3 = os.path.join(self.tmpdir, "c")
        n = q.enqueue_batch([p1, p2, p3])
        assert n == 3
        assert q.summary()["pending"] == 3

    def test_dedup_enqueue(self):
        q = IngestQueue(self.tmpdir)
        p1 = os.path.join(self.tmpdir, "a")
        p2 = os.path.join(self.tmpdir, "b")
        p3 = os.path.join(self.tmpdir, "d")
        q.enqueue_batch([p1, p2])
        n = q.enqueue_batch([p1, p3])
        assert n == 1  # only /d is new
        assert q.summary()["total"] == 3

    def test_process_flow(self):
        q = IngestQueue(self.tmpdir)
        p1 = os.path.join(self.tmpdir, "a")
        p2 = os.path.join(self.tmpdir, "b")
        q.enqueue_batch([p1, p2])
        task = q.get_next_pending()
        assert task is not None
        assert task.status == "pending"
        q.mark_processing(task.id)
        assert task.status == "processing"
        q.mark_done(task.id)
        assert q.summary()["done"] == 1

    def test_retry_logic(self):
        q = IngestQueue(self.tmpdir)
        p = os.path.join(self.tmpdir, "a")
        q.enqueue_batch([p])
        task = q.get_next_pending()
        # First failure -> pending (retry 1)
        q.mark_processing(task.id)
        q.mark_failed(task.id)
        assert task.status == "pending"
        # Second failure -> pending (retry 2)
        q.mark_processing(task.id)
        q.mark_failed(task.id)
        assert task.status == "pending"
        # Third failure -> failed (max retries reached)
        q.mark_processing(task.id)
        q.mark_failed(task.id)
        assert task.status == "failed"

    def test_persistence(self):
        p1 = os.path.join(self.tmpdir, "a")
        p2 = os.path.join(self.tmpdir, "b")
        q1 = IngestQueue(self.tmpdir)
        q1.enqueue_batch([p1, p2])
        q1.mark_processing(q1.tasks[0].id)

        q2 = IngestQueue(self.tmpdir)
        assert q2.summary()["total"] == 2
        assert q2.summary()["processing"] == 1

    def test_cancel(self):
        q = IngestQueue(self.tmpdir)
        p = os.path.join(self.tmpdir, "a")
        q.enqueue_batch([p])
        task = q.get_next_pending()
        assert q.cancel(task.id)
        assert task.status == "cancelled"

    def test_clear_completed(self):
        q = IngestQueue(self.tmpdir)
        p1 = os.path.join(self.tmpdir, "a")
        p2 = os.path.join(self.tmpdir, "b")
        q.enqueue_batch([p1, p2])
        q.mark_processing(q.tasks[0].id)
        q.mark_done(q.tasks[0].id)
        # Fail second task
        q.mark_processing(q.tasks[1].id)
        q.mark_failed(q.tasks[1].id)
        q.mark_processing(q.tasks[1].id)
        q.mark_failed(q.tasks[1].id)
        q.mark_processing(q.tasks[1].id)
        q.mark_failed(q.tasks[1].id)

        cleared = q.clear_completed()
        assert cleared >= 1
