"""/health: which Akamai services Vouch is using right now (same shape as the Akamai starter:
``{"status": "ok", <role>: {"state": live|fallback|off|error, "detail": ...}}``).

Probes that hit the network are cached for ``PROBE_TTL_S`` so the frontend's 5-second health
poll does not burn the inference rate budget. Details never contain secrets.
"""

from __future__ import annotations

import html
import threading
import time
from dataclasses import dataclass, field

import httpx

from .. import __version__
from ..intake.extract import ocr_status
from ..policy import cedar_available
from ..service import VouchService

PROBE_TTL_S = 30.0

State = str  # live | fallback | off | error


@dataclass
class Role:
    name: str
    title: str
    akamai_service: str
    state: State
    detail: str
    latency_ms: int | None = None

    def as_dict(self) -> dict:
        d = {"state": self.state, "detail": self.detail, "akamai_service": self.akamai_service}
        if self.latency_ms is not None:
            d["latency_ms"] = self.latency_ms
        return d


@dataclass
class _Cached:
    at: float = 0.0
    value: tuple[bool, str, int | None] = (False, "", None)


@dataclass
class HealthProbes:
    """Caches the expensive probes (inference, model server, bucket, database)."""

    service: VouchService
    ttl_s: float = PROBE_TTL_S
    _cache: dict[str, _Cached] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _cached(self, key: str, fn) -> tuple[bool, str, int | None]:
        with self._lock:
            c = self._cache.setdefault(key, _Cached())
            if time.monotonic() - c.at < self.ttl_s and c.at:
                return c.value
        t0 = time.monotonic()
        try:
            ok, detail = fn()
        except Exception as exc:  # pragma: no cover - defensive
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        value = (ok, detail, int((time.monotonic() - t0) * 1000))
        with self._lock:
            self._cache[key] = _Cached(at=time.monotonic(), value=value)
        return value

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()

    # ------------------------------------------------------------ probes ----
    def inference(self) -> tuple[bool, str, int | None]:
        return self._cached("inference", self.service.engine.llm.inference.probe)

    def database(self) -> tuple[bool, str, int | None]:
        return self._cached("database", self.service.store.ping)

    def object_storage(self) -> tuple[bool, str, int | None]:
        return self._cached("object_storage", self.service.attachments.ping)

    def model_server(self) -> tuple[bool, str, int | None]:
        url = self.service.settings.model_server_url.rstrip("/")

        def probe() -> tuple[bool, str]:
            r = httpx.get(f"{url}/health", timeout=3.0)
            r.raise_for_status()
            return True, f"{url} · HTTP {r.status_code}"

        return self._cached("model_server", probe)

    def decider(self) -> tuple[bool, str, int | None]:
        classifier = self.service.engine.classifier

        def probe() -> tuple[bool, str]:
            client = classifier.client
            if client is None:
                return False, "no decider client"
            info = client.health()
            model = info.get("model") or info.get("checkpoint") or "?"
            return True, f"{model} on {info.get('device', '?')} · threshold {classifier.threshold:.2f}"

        return self._cached("decider", probe)


def build_roles(service: VouchService, probes: HealthProbes) -> list[Role]:
    s = service.settings
    roles: list[Role] = []

    # Hosted inference (chat) --------------------------------------------------
    llm = service.engine.llm
    if llm.live:
        ok, detail, ms = probes.inference()
        roles.append(
            Role(
                "inference",
                "Hosted inference · chat",
                "Akamai Cloud Inference (OpenAI-compatible)",
                "live" if ok else "error",
                f"{s.akamai_chat_model} @ {s.akamai_base_url}" + (f" · {detail}" if not ok else ""),
                ms,
            )
        )
    else:
        roles.append(
            Role(
                "inference",
                "Hosted inference · chat",
                "Akamai Cloud Inference (OpenAI-compatible)",
                "fallback",
                "AKAMAI_INFERENCE_API_KEY not set → deterministic templates (intake quotes, investigator, explainer)",
            )
        )

    # Embeddings -----------------------------------------------------------------
    emb = llm.embedder_or_none()
    roles.append(
        Role(
            "embeddings",
            "Hosted inference · embeddings",
            "Akamai Cloud Inference (hackathon-embedding, 1024-dim)",
            "live" if emb is not None else "fallback",
            (
                f"{s.akamai_embedding_model} · {service.vendors_indexed} vendors indexed · "
                f"cache hits {llm.embedder.hits} / misses {llm.embedder.misses}"
                if emb is not None
                else "no key → rapidfuzz name/address matching only"
            ),
        )
    )

    # Private model server -------------------------------------------------------
    if s.model_server_url:
        ok, detail, ms = probes.model_server()
        roles.append(
            Role(
                "model_server",
                "Private model server (VPC)",
                "Linode in the model subnet, no public interface",
                "live" if ok else "error",
                detail,
                ms,
            )
        )
    else:
        roles.append(
            Role(
                "model_server",
                "Private model server (VPC)",
                "Linode in the model subnet, no public interface",
                "off",
                "VOUCH_MODEL_SERVER_URL not set (deployed by infra/terraform/akamai)",
            )
        )

    # Database -------------------------------------------------------------------
    ok, detail, ms = probes.database()
    roles.append(
        Role(
            "database",
            "Audit database",
            "Akamai Managed Database · PostgreSQL + pgvector",
            ("live" if ok else "error") if s.is_postgres else "fallback",
            detail if s.is_postgres else f"DATABASE_URL not set → SQLite at {s.data_dir / 'vouch.sqlite3'}",
            ms,
        )
    )

    # Object storage -------------------------------------------------------------
    if s.has_bucket:
        ok, detail, ms = probes.object_storage()
        roles.append(
            Role(
                "object_storage",
                "Attachments & model weights",
                "Akamai Object Storage (S3 API)",
                "live" if ok else "error",
                detail,
                ms,
            )
        )
    else:
        roles.append(
            Role(
                "object_storage",
                "Attachments & model weights",
                "Akamai Object Storage (S3 API)",
                "fallback",
                f"OBJ_* not set → local disk at {s.data_dir / 'attachments'}",
            )
        )

    # Network pieces (reported from deployment metadata; verified by scripts/verify_deploy.sh)
    roles.append(
        Role(
            "nodebalancer",
            "TLS entry point",
            "Akamai NodeBalancer",
            "live" if s.behind_nodebalancer else "off",
            "requests arrive via the NodeBalancer (VOUCH_BEHIND_NODEBALANCER=1)"
            if s.behind_nodebalancer
            else "direct access (local dev)",
        )
    )
    roles.append(
        Role(
            "firewall",
            "Cloud Firewall",
            "Akamai Cloud Firewall",
            "live" if s.firewall_label else "off",
            s.firewall_label or "not attached (local dev)",
        )
    )
    roles.append(
        Role(
            "vpc",
            "VPC (ingress / model / data subnets)",
            "Akamai VPC",
            "live" if s.vpc_label else "off",
            s.vpc_label or "not attached (local dev)",
        )
    )

    # Settlement rail and the risk model ----------------------------------------------
    adapter = service.engine.adapter
    roles.append(
        Role(
            "settlement",
            "Settlement rail",
            "XRPL testnet (atomic Batch, idempotent) · mock ledger fallback",
            "live" if adapter.name == "xrpl" else "fallback",
            f"{adapter.name} · {adapter.network}"
            + (
                ""
                if adapter.name == "xrpl"
                else " · set SETTLEMENT_ADAPTER=xrpl + XRPL_WALLET_SEED for real tx ids"
            ),
        )
    )
    scorer = service.engine.scorer()
    scorer_name = getattr(scorer, "name", "?")
    roles.append(
        Role(
            "risk_model",
            "Risk model (PyTorch + LIME)",
            "vouch-risk: entity embeddings, autoencoder, per-class heads, legitimacy head",
            "live" if scorer_name in ("local-torch", "inference-service") else "fallback",
            f"{scorer_name} {getattr(scorer, 'version', '')}".strip()
            + ("" if scorer_name != "heuristic-fallback" else " · run `make train-vouch` to train the model"),
        )
    )

    # Local controls worth showing to judges ---------------------------------------
    roles.append(
        Role(
            "policy_engine",
            "Policy engine",
            "Cedar (default-deny) · projects/vouch/policies/vouch.cedar",
            "live" if cedar_available() else "fallback",
            "cedarpy evaluating vouch.cedar" if cedar_available() else "python mirror of the Cedar rules",
        )
    )
    # A missing engine is an error, not "off": the API accepts image invoices either way, and without an
    # engine every PNG/JPEG invoice is held as unreadable (R_OCR_UNAVAILABLE). Installed by the Dockerfile.
    ocr = ocr_status()
    roles.append(
        Role(
            "ocr",
            "Image OCR (PNG / JPEG invoices, scanned PDFs)",
            "local tesseract-ocr in the API container (pytesseract) · rapidocr fallback",
            "live" if ocr["state"] == "live" else "error",
            ocr["detail"],
        )
    )

    # Strands Decider (advisory intake routing; AWS sponsor model, self-hosted) ------------------------
    classifier = service.engine.classifier
    stats = classifier.snapshot()
    counts = f"routed {stats['classified']} · decider {stats['decider']} · chat {stats['hackathon-chat']} · deterministic {stats['deterministic']}"
    if classifier.enabled:
        ok, detail, ms = probes.decider()
        roles.append(
            Role(
                "decider",
                "Intake classifier (Strands Decider 2B)",
                "self-hosted strands-decider server (CPU Linode in the VPC) · advisory routing only",
                "live" if ok else "error",
                (
                    detail
                    if ok
                    else f"{s.effective_decider_url} unreachable → hackathon-chat classifier ({detail})"
                )
                + f" · {counts}",
                ms,
            )
        )
    else:
        roles.append(
            Role(
                "decider",
                "Intake classifier (Strands Decider 2B)",
                "self-hosted strands-decider server (CPU Linode in the VPC) · advisory routing only",
                "off",
                (
                    "DECIDER_ENABLED=false"
                    if s.decider_enabled is False
                    else "DECIDER_URL not set (deployed by infra/terraform/akamai, or `make decider-local`)"
                )
                + f" → deterministic routing · {counts}",
            )
        )
    return roles


def health_json(service: VouchService, probes: HealthProbes) -> dict:
    roles = build_roles(service, probes)
    errors = [r.name for r in roles if r.state == "error"]
    s = service.settings
    llm = service.engine.llm
    out: dict = {
        "status": "ok" if not errors else "degraded",
        "service": "vouch-api",
        "app": s.app_name,
        "version": __version__,
        "region": s.region,
        "uptime_s": service.uptime_s(),
        "llm_mode": llm.mode,
        "payments": sum(len(r.cards) for r in service.engine.runs.values()),
        "runs": len(service.engine.runs),
        "settlement_adapter": service.engine.adapter.name,
        "scorer": getattr(service.engine.scorer(), "name", "?"),
        "errors": errors,
    }
    for r in roles:
        out[r.name] = r.as_dict()
    return out


_COLORS = {"live": "#1b7f3b", "fallback": "#9a6700", "off": "#6b7280", "error": "#b91c1c"}


def health_html(service: VouchService, probes: HealthProbes) -> str:
    roles = build_roles(service, probes)
    s = service.settings
    rows = "\n".join(
        "<tr>"
        f"<td><strong>{html.escape(r.title)}</strong><br><small>{html.escape(r.akamai_service)}</small></td>"
        f"<td><span class='pill' style='background:{_COLORS[r.state]}'>{r.state}</span></td>"
        f"<td>{html.escape(r.detail)}{f' <small>({r.latency_ms} ms)</small>' if r.latency_ms is not None else ''}</td>"
        "</tr>"
        for r in roles
    )
    live = sum(1 for r in roles if r.state == "live")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{html.escape(s.app_name)} · health</title>
<meta http-equiv="refresh" content="15">
<style>
body{{font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:2rem auto;max-width:960px;color:#111827;padding:0 1rem}}
h1{{font-size:1.4rem;margin:0 0 .25rem}} .sub{{color:#6b7280;margin-bottom:1.25rem}}
table{{border-collapse:collapse;width:100%}} td{{padding:.6rem .5rem;border-top:1px solid #e5e7eb;vertical-align:top}}
.pill{{color:#fff;border-radius:999px;padding:.1rem .6rem;font-size:.8rem;text-transform:uppercase;letter-spacing:.04em}}
small{{color:#6b7280}} a{{color:#1d4ed8}}
</style></head><body>
<h1>{html.escape(s.app_name)} · Akamai services in use</h1>
<div class="sub">{live}/{len(roles)} live · region {html.escape(s.region)} · llm_mode {service.engine.llm.mode} ·
{sum(len(r.cards) for r in service.engine.runs.values())} payments in queue · uptime {service.uptime_s()} s ·
<a href="/health?format=json">JSON</a> · <a href="/docs">API docs</a> · <a href="/v1/netz">/netz</a></div>
<table>{rows}</table>
<p><small>States: <b>live</b> = the Akamai service answered · <b>fallback</b> = local stand-in in use ·
<b>off</b> = not configured in this environment · <b>error</b> = configured but unreachable.
No secrets are shown. Refreshes every 15 s.</small></p>
</body></html>"""
