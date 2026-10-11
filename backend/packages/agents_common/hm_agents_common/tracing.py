"""OpenTelemetry tracing for Strands agents. No-op unless an exporter is configured.

Set OTEL_EXPORTER_OTLP_ENDPOINT (e.g. http://localhost:4318 for a local Jaeger/collector) and/or
OTEL_CONSOLE_EXPORTER=true. Strands emits spans for agent invocations, model calls and tool calls.
"""

from __future__ import annotations

import logging
import os

from hm_agents_common.settings import AgentSettings, get_agent_settings

log = logging.getLogger(__name__)
_configured = False


def setup_tracing(service_name: str | None = None, settings: AgentSettings | None = None) -> bool:
    global _configured
    if _configured:
        return True
    s = settings or get_agent_settings()
    if not (s.otel_exporter_otlp_endpoint or s.otel_console_exporter):
        return False
    os.environ.setdefault("OTEL_SERVICE_NAME", service_name or s.otel_service_name or "hackmidwest-agent")
    if s.otel_exporter_otlp_endpoint:
        os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", s.otel_exporter_otlp_endpoint)

    from strands.telemetry import StrandsTelemetry

    telemetry = StrandsTelemetry()
    if s.otel_exporter_otlp_endpoint:
        telemetry.setup_otlp_exporter()
    if s.otel_console_exporter:
        telemetry.setup_console_exporter()
    _configured = True
    log.info("tracing enabled", extra={"service": os.environ["OTEL_SERVICE_NAME"]})
    return True
