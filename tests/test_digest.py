from datetime import UTC, datetime, timedelta

from beddington.digest import build_digest
from beddington.models import Event, NightReport


def test_digest_reports_no_sustained_episodes() -> None:
    started = datetime(2026, 6, 18, tzinfo=UTC)
    report = NightReport(
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

    digest = build_digest(report)

    assert "did not detect any sustained crying episodes" in digest
    assert "locally" in digest
