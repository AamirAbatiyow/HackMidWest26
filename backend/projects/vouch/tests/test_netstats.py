"""Tests for the netstats API router and timing helper."""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from vouch import main
from vouch.audit import AuditStore
from vouch.service import VouchService
from vouch.timing import TIMING, RingStats, TimingRegistry, timed, timed_decorator


class TestRingStats:
    """Tests for the RingStats ring buffer."""

    def test_empty_ring_returns_none(self):
        ring = RingStats("test", max_size=10)
        assert ring.p50() is None
        assert ring.p95() is None
        assert ring.count() == 0
        assert ring.latest() is None

    def test_single_sample(self):
        ring = RingStats("test", max_size=10)
        ring.record(42.5)
        assert ring.p50() == pytest.approx(42.5)
        assert ring.p95() == pytest.approx(42.5)
        assert ring.count() == 1
        assert ring.latest() == pytest.approx(42.5)

    def test_multiple_samples_percentiles(self):
        ring = RingStats("test", max_size=100)
        for i in range(1, 101):
            ring.record(float(i))
        assert ring.count() == 100
        assert 49.0 <= ring.p50() <= 52.0
        assert 94.0 <= ring.p95() <= 96.0
        assert ring.latest() == pytest.approx(100.0)

    def test_ring_buffer_eviction(self):
        ring = RingStats("test", max_size=5)
        for i in range(1, 11):
            ring.record(float(i))
        assert ring.count() == 5
        assert ring.latest() == pytest.approx(10.0)
        assert 6.0 <= ring.p50() <= 10.0

    def test_stats_dict(self):
        ring = RingStats("test", max_size=10)
        ring.record(10.0)
        ring.record(20.0)
        stats = ring.stats()
        assert "p50" in stats
        assert "p95" in stats
        assert "count" in stats
        assert "latest" in stats
        assert stats["count"] == 2

    def test_thread_safety(self):
        ring = RingStats("test", max_size=1000)
        errors = []

        def record_samples():
            try:
                for i in range(100):
                    ring.record(float(i))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_samples) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert ring.count() == 1000


class TestTimingRegistry:
    """Tests for the TimingRegistry."""

    def test_empty_registry(self):
        registry = TimingRegistry()
        stats = registry.all_stats()
        assert stats == {}

    def test_record_and_retrieve(self):
        registry = TimingRegistry(ring_size=100)
        registry.record("step1", 10.0)
        registry.record("step1", 20.0)
        registry.record("step2", 5.0)

        assert registry.p50("step1") is not None
        assert registry.stats("step1")["count"] == 2
        assert registry.stats("step2")["count"] == 1

    def test_all_stats(self):
        registry = TimingRegistry()
        registry.record("a", 1.0)
        registry.record("b", 2.0)
        all_stats = registry.all_stats()
        assert "a" in all_stats
        assert "b" in all_stats

    def test_clear(self):
        registry = TimingRegistry()
        registry.record("test", 1.0)
        assert registry.stats("test")["count"] == 1
        registry.clear()
        assert registry.all_stats() == {}


class TestTimedContextManager:
    """Tests for the timed context manager."""

    def test_basic_timing(self):
        registry = TimingRegistry()
        with timed("test_step", registry):
            time.sleep(0.01)
        stats = registry.stats("test_step")
        assert stats["count"] == 1
        assert stats["latest"] is not None
        assert stats["latest"] >= 10.0

    def test_timing_with_exception(self):
        registry = TimingRegistry()
        try:
            with timed("error_step", registry):
                raise ValueError("test error")
        except ValueError:
            pass
        stats = registry.stats("error_step")
        assert stats["count"] == 1

    def test_uses_global_timing_by_default(self):
        initial_count = TIMING.stats("global_test").get("count", 0)
        with timed("global_test"):
            pass
        assert TIMING.stats("global_test")["count"] == initial_count + 1


class TestTimedDecorator:
    """Tests for the timed_decorator."""

    def test_decorator_records_timing(self):
        registry = TimingRegistry()

        @timed_decorator("decorated_fn", registry)
        def slow_function():
            time.sleep(0.01)
            return "result"

        result = slow_function()
        assert result == "result"
        stats = registry.stats("decorated_fn")
        assert stats["count"] == 1
        assert stats["latest"] >= 10.0

    def test_decorator_preserves_exceptions(self):
        registry = TimingRegistry()

        @timed_decorator("error_fn", registry)
        def error_function():
            raise RuntimeError("test")

        with pytest.raises(RuntimeError, match="test"):
            error_function()
        assert registry.stats("error_fn")["count"] == 1


@pytest.fixture
def client(settings, tmp_path):
    settings = settings.model_copy(update={"data_dir": tmp_path, "seed_demo": False})
    service = VouchService(settings, store=AuditStore("sqlite://"), seed_demo=False, restore=False)
    service.seed(run_demo=True, background_vendors=10)
    main.set_service(service)
    try:
        yield TestClient(main.app)
    finally:
        main.set_service(None)


class TestNetstatsAPI:
    """Tests for the /v1/latency and /v1/topology endpoints."""

    def test_latency_endpoint_returns_structure(self, client):
        response = client.get("/v1/latency")
        assert response.status_code == 200
        data = response.json()

        assert "updated_at" in data
        assert "region" in data
        assert "pipeline_steps" in data
        assert "inference" in data
        assert "decider" in data
        assert "postgres" in data
        assert "object_storage" in data
        assert "tiers" in data

    def test_latency_pipeline_steps(self, client):
        response = client.get("/v1/latency")
        data = response.json()

        steps = data["pipeline_steps"]
        expected_steps = [
            "reader",
            "sender_check",
            "vendor_resolution",
            "detector_amount",
            "detector_bank",
            "detector_duplicate",
            "detector_ring",
            "scorer",
            "policy",
            "writer",
        ]
        for step in expected_steps:
            assert step in steps
            assert "p50_ms" in steps[step]
            assert "p95_ms" in steps[step]
            assert "count" in steps[step]

    def test_latency_inference_stats(self, client):
        response = client.get("/v1/latency")
        data = response.json()

        inference = data["inference"]
        assert "hackathon-chat" in inference
        assert "hackathon-embedding" in inference

        chat = inference["hackathon-chat"]
        assert "model" in chat
        assert "live" in chat
        assert "p50_ms" in chat
        assert "p95_ms" in chat

    def test_latency_decider_stats(self, client):
        response = client.get("/v1/latency")
        data = response.json()

        decider = data["decider"]
        assert "engine" in decider
        assert "engines_available" in decider
        assert "p50_ms" in decider
        assert "p95_ms" in decider

    def test_latency_tiers(self, client):
        response = client.get("/v1/latency")
        data = response.json()

        tiers = data["tiers"]
        expected_tiers = ["ingress", "app", "model", "data"]
        for tier in expected_tiers:
            assert tier in tiers
            assert "name" in tiers[tier]
            assert "subnet" in tiers[tier]
            assert "products" in tiers[tier]
            assert "configured" in tiers[tier]

    def test_topology_endpoint_returns_structure(self, client):
        response = client.get("/v1/topology")
        assert response.status_code == 200
        data = response.json()

        assert "updated_at" in data
        assert "region" in data
        assert "vpc" in data
        assert "firewall" in data
        assert "nodebalancer" in data
        assert "tiers" in data
        assert "nodes" in data
        assert "edges" in data

    def test_topology_nodes(self, client):
        response = client.get("/v1/topology")
        data = response.json()

        nodes = data["nodes"]
        assert isinstance(nodes, list)
        assert len(nodes) >= 7

        node_ids = {n["id"] for n in nodes}
        expected_ids = {
            "internet",
            "nodebalancer",
            "firewall",
            "api",
            "model_server",
            "inference",
            "postgres",
            "object_storage",
        }
        assert expected_ids <= node_ids

        for node in nodes:
            assert "id" in node
            assert "label" in node
            assert "x" in node
            assert "y" in node

    def test_topology_edges(self, client):
        response = client.get("/v1/topology")
        data = response.json()

        edges = data["edges"]
        assert isinstance(edges, list)
        assert len(edges) >= 5

        for edge in edges:
            assert "id" in edge
            assert "from" in edge
            assert "to" in edge
            assert "private" in edge

    def test_topology_tiers(self, client):
        response = client.get("/v1/topology")
        data = response.json()

        tiers = data["tiers"]
        expected_tiers = ["ingress", "app", "model", "data"]
        for tier in expected_tiers:
            assert tier in tiers
            tier_info = tiers[tier]
            assert "name" in tier_info
            assert "subnet" in tier_info
            assert "products" in tier_info
            assert "description" in tier_info

    def test_topology_vpc_and_firewall(self, client):
        response = client.get("/v1/topology")
        data = response.json()

        vpc = data["vpc"]
        assert "label" in vpc
        assert "configured" in vpc

        firewall = data["firewall"]
        assert "label" in firewall
        assert "configured" in firewall
        assert "rules" in firewall
