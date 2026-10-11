"""`vouch-smoke-llm` must skip cleanly (exit 0) when the Akamai key is not configured."""

from __future__ import annotations

import pytest

from vouch.config import reset_settings_cache
from vouch.llm import smoke


def test_smoke_llm_skips_without_key(monkeypatch, capsys):
    monkeypatch.delenv("AKAMAI_INFERENCE_API_KEY", raising=False)
    reset_settings_cache()
    with pytest.raises(SystemExit) as exc:
        smoke.main()
    assert exc.value.code == 0
    assert "SKIP" in capsys.readouterr().out
    reset_settings_cache()
