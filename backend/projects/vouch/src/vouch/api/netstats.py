"""/v1/latency and /v1/topology: Network and latency stats for the Akamai networking judge.

Exposes per-pipeline-step timings, Akamai inference latency, Postgres and Object Storage RTT,
and a tier map showing the VPC/subnet/firewall/NodeBalancer layout.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from ..timing import DECIDER_ENGINES, DECIDER_STEP, PIPELINE_STEPS, TIMING
from .state import get_service

router = APIRouter(prefix="/v1", tags=["netstats"])


AKAMAI_TIER_MAP = {
    "ingress": {
        "name": "Ingress Tier",
        "subnet": "10.0.1.0/24",
        "products": ["Akamai NodeBalancer", "Akamai Cloud Firewall"],
        "description": "TLS termination and DDoS protection",
    },
    "app": {
        "name": "Application Tier",
        "subnet": "10.0.2.0/24",
        "products": ["Dedicated-CPU Linode", "Akamai VPC"],
        "description": "Vouch API servers",
    },
    "model": {
        "name": "Model Tier",
        "subnet": "10.0.3.0/24",
        "products": ["Dedicated-CPU Linode", "Akamai Cloud Inference"],
        "description": "Private model server and hosted inference",
    },
    "data": {
        "name": "Data Tier",
        "subnet": "10.0.4.0/24",
        "products": ["Akamai Managed Postgres (pgvector)", "Akamai Object Storage"],
        "description": "Persistent storage for audit trail and attachments",
    },
}

FIREWALL_RULES = [
    {
        "id": "fw-1",
        "direction": "inbound",
        "protocol": "TCP",
        "ports": "443",
        "source": "0.0.0.0/0",
        "action": "ACCEPT",
        "label": "HTTPS from internet",
    },
    {
        "id": "fw-2",
        "direction": "inbound",
        "protocol": "TCP",
        "ports": "80",
        "source": "0.0.0.0/0",
        "action": "ACCEPT",
        "label": "HTTP redirect",
    },
    {
        "id": "fw-3",
        "direction": "inbound",
        "protocol": "TCP",
        "ports": "22",
        "source": "10.0.0.0/8",
        "action": "ACCEPT",
        "label": "SSH from VPC",
    },
    {
        "id": "fw-4",
        "direction": "outbound",
        "protocol": "TCP",
        "ports": "5432",
        "destination": "10.0.4.0/24",
        "action": "ACCEPT",
        "label": "Postgres",
    },
    {
        "id": "fw-5",
        "direction": "outbound",
        "protocol": "TCP",
        "ports": "443",
        "destination": "*.akamai-workshops.com",
        "action": "ACCEPT",
        "label": "Hosted inference",
    },
    {
        "id": "fw-6",
        "direction": "inbound",
        "protocol": "*",
        "ports": "*",
        "source": "0.0.0.0/0",
        "action": "DROP",
        "label": "Default deny",
    },
]


def _safe_probe_latency(probe_fn) -> dict[str, Any]:
    """Run a probe function and return latency stats; tolerate failures."""
    try:
        ok, detail, ms = probe_fn()
        return {"ok": ok, "detail": detail, "latency_ms": ms}
    except Exception as e:
        return {"ok": False, "detail": str(e), "latency_ms": None}


def _get_inference_stats(service) -> dict[str, Any]:
    """Get Akamai hosted inference latency and token stats."""
    llm = service.engine.llm
    s = service.settings
    return {
        "hackathon-chat": {
            "model": s.akamai_chat_model,
            "base_url": s.akamai_base_url,
            "live": llm.live,
            "p50_ms": TIMING.p50("hackathon-chat"),
            "p95_ms": TIMING.p95("hackathon-chat"),
            "count": TIMING.stats("hackathon-chat").get("count", 0),
            "latest_ms": TIMING.stats("hackathon-chat").get("latest"),
        },
        "hackathon-embedding": {
            "model": s.akamai_embedding_model,
            "base_url": s.akamai_base_url,
            "live": llm.embedder_or_none() is not None,
            "p50_ms": TIMING.p50("hackathon-embedding"),
            "p95_ms": TIMING.p95("hackathon-embedding"),
            "count": TIMING.stats("hackathon-embedding").get("count", 0),
            "latest_ms": TIMING.stats("hackathon-embedding").get("latest"),
        },
    }


def _get_decider_stats(service) -> dict[str, Any]:
    """Strands Decider 2B: which engine settles ambiguous intake routes, and what its calls cost in time.

    ``engine`` is the classifier's live role: ``decider`` when a Decider server is configured, otherwise
    the ``hackathon-chat`` classifier when the LLM is, otherwise ``deterministic`` (code routes alone).
    p50/p95/count are the ``decider`` timing ring, which ``IntakeClassifier`` feeds with one sample per
    answered Decider question; ``latest_ms`` is ``HttpDeciderClient.last_latency_ms``, the latency the
    server reported for the most recent call. ``classifier`` is ``IntakeClassifier.snapshot()``: how many
    submissions each engine routed, model decisions, strict-schema validation failures, kickbacks, owner
    reviews, and whether the client is cooling down after a failure (and why).
    """
    classifier = service.engine.classifier
    snapshot = classifier.snapshot()
    if snapshot["enabled"]:
        engine = "decider"
    elif classifier.has_model:
        engine = "hackathon-chat"
    else:
        engine = "deterministic"
    ring = TIMING.stats(DECIDER_STEP)
    latest = getattr(classifier.client, "last_latency_ms", None)
    return {
        "engine": engine,
        "engines_available": DECIDER_ENGINES,
        "client": snapshot["client"],
        "p50_ms": ring.get("p50"),
        "p95_ms": ring.get("p95"),
        "count": ring.get("count", 0),
        "latest_ms": latest if latest is not None else ring.get("latest"),
        "classifier": snapshot,
    }


def _get_tier_health(service) -> dict[str, dict]:
    """Get health and RTT between tiers when configured."""
    s = service.settings
    tiers = {}
    for tier_id, tier_info in AKAMAI_TIER_MAP.items():
        tiers[tier_id] = {
            **tier_info,
            "configured": False,
            "healthy": None,
            "rtt_ms": None,
        }

    if s.behind_nodebalancer:
        tiers["ingress"]["configured"] = True
        tiers["ingress"]["healthy"] = True
        tiers["ingress"]["rtt_ms"] = TIMING.p50("ingress_rtt")

    if s.vpc_label:
        tiers["app"]["configured"] = True
        tiers["app"]["healthy"] = True
        tiers["app"]["rtt_ms"] = TIMING.p50("app_rtt")

    if s.model_server_url:
        tiers["model"]["configured"] = True
        tiers["model"]["rtt_ms"] = TIMING.p50("model_rtt")

    if s.is_postgres:
        tiers["data"]["configured"] = True
        ping_stats = _safe_probe_latency(service.store.ping)
        tiers["data"]["healthy"] = ping_stats.get("ok")
        tiers["data"]["rtt_ms"] = ping_stats.get("latency_ms")

    if s.has_bucket:
        bucket_stats = _safe_probe_latency(service.attachments.ping)
        if tiers["data"]["rtt_ms"] is None:
            tiers["data"]["rtt_ms"] = bucket_stats.get("latency_ms")
        tiers["data"]["configured"] = True

    return tiers


@router.get("/latency")
def get_latency() -> dict:
    """Return per-pipeline-step timings, rolling p50/p95 over the last N runs.

    Includes Akamai hosted inference latency, Decider call latency, Postgres query latency,
    and Object Storage round-trip.
    """
    service = get_service()
    s = service.settings

    pipeline_stats = {}
    for step in PIPELINE_STEPS:
        stats = TIMING.stats(step)
        pipeline_stats[step] = {
            "p50_ms": stats.get("p50"),
            "p95_ms": stats.get("p95"),
            "count": stats.get("count", 0),
            "latest_ms": stats.get("latest"),
        }

    postgres_stats = _safe_probe_latency(service.store.ping)
    object_storage_stats = (
        _safe_probe_latency(service.attachments.ping)
        if s.has_bucket
        else {"ok": None, "detail": "Object Storage not configured", "latency_ms": None}
    )

    waterfall = []
    last_run_id = None
    if service.engine.runs:
        last_run_id = list(service.engine.runs.keys())[-1]
        for step in PIPELINE_STEPS:
            step_key = f"run:{last_run_id}:{step}"
            latest = TIMING.stats(step_key).get("latest")
            waterfall.append(
                {
                    "step": step,
                    "latency_ms": latest,
                }
            )

    return {
        "updated_at": datetime.now(UTC).isoformat(),
        "region": s.region,
        "pipeline_steps": pipeline_stats,
        "inference": _get_inference_stats(service),
        "decider": _get_decider_stats(service),
        "postgres": {
            "configured": s.is_postgres,
            "ok": postgres_stats.get("ok"),
            "latency_ms": postgres_stats.get("latency_ms"),
            "p50_ms": TIMING.p50("postgres"),
            "p95_ms": TIMING.p95("postgres"),
        },
        "object_storage": {
            "configured": s.has_bucket,
            "ok": object_storage_stats.get("ok"),
            "latency_ms": object_storage_stats.get("latency_ms"),
            "p50_ms": TIMING.p50("object_storage"),
            "p95_ms": TIMING.p95("object_storage"),
        },
        "tiers": _get_tier_health(service),
        "last_run_waterfall": {
            "run_id": last_run_id,
            "steps": waterfall,
        }
        if last_run_id
        else None,
    }


@router.get("/topology")
def get_topology() -> dict:
    """Return the static VPC/subnet/firewall/NodeBalancer layout from config.

    Used by the frontend to draw the topology diagram.
    """
    service = get_service()
    s = service.settings

    nodes = [
        {
            "id": "internet",
            "label": "Internet",
            "tier": None,
            "product": None,
            "x": 50,
            "y": 100,
        },
        {
            "id": "nodebalancer",
            "label": "NodeBalancer",
            "tier": "ingress",
            "product": "Akamai NodeBalancer",
            "configured": s.behind_nodebalancer,
            "x": 200,
            "y": 100,
        },
        {
            "id": "firewall",
            "label": "Cloud Firewall",
            "tier": "ingress",
            "product": "Akamai Cloud Firewall",
            "configured": bool(s.firewall_label),
            "x": 350,
            "y": 100,
        },
        {
            "id": "api",
            "label": "Vouch API",
            "tier": "app",
            "product": "Dedicated-CPU Linode",
            "configured": True,
            "x": 500,
            "y": 100,
        },
        {
            "id": "model_server",
            "label": "Model Server",
            "tier": "model",
            "product": "Dedicated-CPU Linode",
            "configured": bool(s.model_server_url),
            "x": 650,
            "y": 50,
        },
        {
            "id": "inference",
            "label": "Hosted Inference",
            "tier": "model",
            "product": "Akamai Cloud Inference",
            "configured": s.has_llm_key,
            "x": 650,
            "y": 150,
        },
        {
            "id": "postgres",
            "label": "Managed Postgres",
            "tier": "data",
            "product": "Akamai Managed Database",
            "configured": s.is_postgres,
            "x": 800,
            "y": 50,
        },
        {
            "id": "object_storage",
            "label": "Object Storage",
            "tier": "data",
            "product": "Akamai Object Storage",
            "configured": s.has_bucket,
            "x": 800,
            "y": 150,
        },
    ]

    edges = [
        {"id": "e1", "from": "internet", "to": "nodebalancer", "label": "TLS 1.3", "private": False},
        {"id": "e2", "from": "nodebalancer", "to": "firewall", "label": "", "private": True},
        {"id": "e3", "from": "firewall", "to": "api", "label": "", "private": True},
        {"id": "e4", "from": "api", "to": "model_server", "label": "gRPC", "private": True},
        {"id": "e5", "from": "api", "to": "inference", "label": "HTTPS", "private": False},
        {"id": "e6", "from": "api", "to": "postgres", "label": "pgvector", "private": True},
        {"id": "e7", "from": "api", "to": "object_storage", "label": "S3 API", "private": True},
    ]

    return {
        "updated_at": datetime.now(UTC).isoformat(),
        "region": s.region,
        "vpc": {
            "label": s.vpc_label or "Not configured",
            "configured": bool(s.vpc_label),
        },
        "firewall": {
            "label": s.firewall_label or "Not configured",
            "configured": bool(s.firewall_label),
            "rules": FIREWALL_RULES if s.firewall_label else [],
        },
        "nodebalancer": {
            "configured": s.behind_nodebalancer,
        },
        "tiers": AKAMAI_TIER_MAP,
        "nodes": nodes,
        "edges": edges,
    }
