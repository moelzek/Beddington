from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

from beddington.config import LlmConfig
from beddington.llm import polish_digest
from beddington.models import NightReport


class _Response(io.StringIO):
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _report() -> NightReport:
    started = datetime(2026, 6, 18, tzinfo=UTC)
    return NightReport(
        started_at=started,
        finished_at=started + timedelta(seconds=5),
        source="quiet.wav",
        detector="fake",
        threshold=0.25,
        sustained_seconds=1.5,
        windows_processed=9,
        peak_score=0.1,
        events=(),
    )


def _config() -> LlmConfig:
    return LlmConfig(
        enabled=True,
        base_url="http://localhost:1/v1",
        model="test-model",
        api_key="test-key",
    )


def test_polish_digest_keeps_summary_on_empty_content(monkeypatch) -> None:
    def fake_urlopen(*_args: object, **_kwargs: object) -> _Response:
        return _Response('{"choices": [{"message": {"content": "   "}}]}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert (
        polish_digest("deterministic digest", _report(), _config())
        == "deterministic digest"
    )


def test_polish_digest_keeps_summary_on_bad_json(monkeypatch) -> None:
    def fake_urlopen(*_args: object, **_kwargs: object) -> _Response:
        return _Response("{not json")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert (
        polish_digest("deterministic digest", _report(), _config())
        == "deterministic digest"
    )
