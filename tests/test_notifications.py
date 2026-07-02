import urllib.request

from beddington.notifications import LiveViewNotifier


class _Resp:
    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *_a: object) -> bool:
        return False

    def read(self) -> bytes:
        return b""


def test_liveview_notifier_posts_alert(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = LiveViewNotifier(port=8088, token="tok").notify(
        "Cry detected", "score 0.90"
    )

    assert result == {"lan": True}
    assert seen["method"] == "POST"
    assert "/alert?" in seen["url"]
    assert "token=tok" in seen["url"]
    assert "Cry+detected" in seen["url"]


def test_liveview_notifier_without_token_is_noop() -> None:
    # No token -> never touches the network, reports not-delivered.
    assert LiveViewNotifier(token="").notify("x", "y") == {"lan": False}


def test_liveview_notifier_swallows_failures(monkeypatch) -> None:
    def boom(request, timeout=None):  # noqa: ANN001
        raise OSError("server down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    # A missed alert must never crash the monitoring loop.
    assert LiveViewNotifier(token="tok").notify("x", "y") == {"lan": False}
