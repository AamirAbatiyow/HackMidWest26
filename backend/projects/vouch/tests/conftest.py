from datetime import date

import pytest

from hm_settlement import MockSettlementAdapter
from vouch.config import Settings
from vouch.demo import seed
from vouch.engine import VouchEngine
from vouch.llm import LLMRuntime
from vouch.scorer import HeuristicScorer

TODAY = date(2026, 10, 10)


@pytest.fixture
def settings() -> Settings:
    return Settings(scorer="heuristic", llm_mode="offline")


def make_service(settings: Settings, llm: LLMRuntime | None = None, **kw) -> VouchEngine:
    svc = VouchEngine(
        settings=settings,
        llm=llm or LLMRuntime("offline", settings=settings),
        adapter=MockSettlementAdapter(),
        scorer=HeuristicScorer(),
        today=TODAY,
        **kw,
    )
    seed(svc, background_vendors=60)
    return svc


@pytest.fixture
def service(settings) -> VouchEngine:
    return make_service(settings)


@pytest.fixture
def service_factory(settings):
    def build(**kw) -> VouchEngine:
        return make_service(kw.pop("settings", None) or settings, **kw)

    return build
