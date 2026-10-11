"""Strands Decider integration: an advisory routing classifier for invoice intake.

- ``client``        strict wire models + ``HttpDeciderClient`` / ``FakeDeciderClient`` (tests, CI)
- ``classify``      ``IntakeClassifier``: Decider -> hackathon-chat structured output -> deterministic sniffing
- ``intervention``  ``GroundingIntervention``: Strands ``before_tool_call`` Guide for ungrounded intake output

The Decider only routes (format -> parse tool) or adds friction (a kickback hold that needs the owner's
approval). It never produces a fraud or legitimacy verdict and never feeds LIME; the kernel, Cedar and the
owner keep the authority over money.
"""

from .classify import (
    CLASSIFY_PROMPT,
    DEFAULT_THRESHOLD,
    EXTRACTOR_TOOLS,
    FORMAT_CRITERIA,
    TOOL_CRITERIA,
    TOOLS_FOR_FORMAT,
    DocumentProbe,
    FormatDecision,
    IntakeClassification,
    IntakeClassifier,
    KickbackDraft,
    LlmIntakeRouting,
    ToolDecision,
    deterministic_route,
    extractor_for,
    probes_from_documents,
    probes_from_files,
    probes_from_submission,
    render_state,
)
from .client import (
    DEFAULT_MODEL,
    DEFAULT_URL,
    SERVE_HINT,
    Answer,
    ChoiceAnswer,
    DeciderClient,
    DeciderRejected,
    DeciderUnavailable,
    FakeDeciderClient,
    HttpDeciderClient,
    NoulAnswer,
    ScoreAnswer,
    SystemOneResponse,
    choice,
    choice_answer,
    default_answer,
    noul,
    parse_response,
    score,
)
from .intervention import GROUNDED_FIELDS, GroundingIntervention, ungrounded_fields

__all__ = [
    "CLASSIFY_PROMPT",
    "DEFAULT_MODEL",
    "DEFAULT_THRESHOLD",
    "DEFAULT_URL",
    "EXTRACTOR_TOOLS",
    "FORMAT_CRITERIA",
    "GROUNDED_FIELDS",
    "SERVE_HINT",
    "TOOLS_FOR_FORMAT",
    "TOOL_CRITERIA",
    "Answer",
    "ChoiceAnswer",
    "DeciderClient",
    "DeciderRejected",
    "DeciderUnavailable",
    "DocumentProbe",
    "FakeDeciderClient",
    "FormatDecision",
    "GroundingIntervention",
    "HttpDeciderClient",
    "IntakeClassification",
    "IntakeClassifier",
    "KickbackDraft",
    "LlmIntakeRouting",
    "NoulAnswer",
    "ScoreAnswer",
    "SystemOneResponse",
    "ToolDecision",
    "choice",
    "choice_answer",
    "default_answer",
    "deterministic_route",
    "extractor_for",
    "noul",
    "parse_response",
    "probes_from_documents",
    "probes_from_files",
    "probes_from_submission",
    "render_state",
    "score",
    "ungrounded_fields",
]
