from dataclasses import dataclass

import beddington.endpoint as endpoint
from beddington.endpoint import resolve_ollama_target


@dataclass(frozen=True)
class _Cfg:
    host: str = "http://127.0.0.1:11434"
    model: str = "llama3.2:1b"
    upgrade_host: str = ""
    upgrade_model: str = ""
    upgrade_keep_alive: str = "10m"
    upgrade_probe_timeout: float = 1.0
    upgrade_probe_cache_seconds: float = 60.0


def setup_function(_):
    endpoint._PROBE_CACHE.clear()


def test_no_upgrade_host_uses_pi_baseline_and_unloads():
    target = resolve_ollama_target(_Cfg())
    assert target.host == "http://127.0.0.1:11434"
    assert target.model == "llama3.2:1b"
    assert target.keep_alive == 0


def test_reachable_upgrade_host_is_preferred_and_kept_warm(monkeypatch):
    monkeypatch.setattr(endpoint, "_probe", lambda host, timeout: True)
    cfg = _Cfg(upgrade_host="http://desktop.local:11434/", upgrade_model="gemma3:12b")
    target = resolve_ollama_target(cfg)
    assert target.host == "http://desktop.local:11434"
    assert target.model == "gemma3:12b"
    assert target.keep_alive == "10m"


def test_unreachable_upgrade_host_falls_back_to_pi(monkeypatch):
    monkeypatch.setattr(endpoint, "_probe", lambda host, timeout: False)
    cfg = _Cfg(upgrade_host="http://desktop.local:11434", upgrade_model="gemma3:12b")
    target = resolve_ollama_target(cfg)
    assert target.host == "http://127.0.0.1:11434"
    assert target.model == "llama3.2:1b"
    assert target.keep_alive == 0


def test_upgrade_model_defaults_to_primary_when_blank(monkeypatch):
    monkeypatch.setattr(endpoint, "_probe", lambda host, timeout: True)
    cfg = _Cfg(upgrade_host="http://desktop.local:11434")
    target = resolve_ollama_target(cfg)
    assert target.model == "llama3.2:1b"


def test_probe_result_is_cached(monkeypatch):
    calls = {"n": 0}

    def counting_probe(host, timeout):
        calls["n"] += 1
        return True

    monkeypatch.setattr(endpoint, "_probe", counting_probe)
    cfg = _Cfg(upgrade_host="http://desktop.local:11434", upgrade_model="gemma3:12b")
    resolve_ollama_target(cfg)
    resolve_ollama_target(cfg)
    assert calls["n"] == 1


def test_persona_upgrade_only_skips_restyle_when_on_pi_baseline(monkeypatch):
    from beddington.config import NarratorConfig
    from beddington import persona

    monkeypatch.setattr(endpoint, "_probe", lambda host, timeout: False)
    called = {"n": 0}

    def counting_call(plain, config):
        called["n"] += 1
        return "If I may, the room is lovely."

    monkeypatch.setattr(persona, "_call_ollama", counting_call)
    cfg = NarratorConfig(
        persona_enabled=True,
        persona_upgrade_only=True,
        upgrade_host="http://desktop.local:11434",
        upgrade_model="gemma3:12b",
    )
    plain = "The room is about 21 degrees Celsius."
    assert persona.paddingtonise(plain, cfg) == plain
    assert called["n"] == 0


def test_persona_upgrade_only_restyles_when_upgrade_reachable(monkeypatch):
    from beddington.config import NarratorConfig
    from beddington import persona

    monkeypatch.setattr(endpoint, "_probe", lambda host, timeout: True)
    monkeypatch.setattr(
        persona,
        "_call_ollama",
        lambda plain, config: "The room is about 21 degrees Celsius, if I may.",
    )
    cfg = NarratorConfig(
        persona_enabled=True,
        persona_upgrade_only=True,
        upgrade_host="http://desktop.local:11434",
        upgrade_model="gemma3:12b",
    )
    plain = "The room is about 21 degrees Celsius."
    assert (
        persona.paddingtonise(plain, cfg)
        == "The room is about 21 degrees Celsius, if I may."
    )


def test_config_loads_upgrade_fields():
    from beddington.config import NarratorConfig, _load_narrator

    cfg = _load_narrator(
        {
            "upgrade_host": "http://desktop.local:11434",
            "upgrade_model": "gemma3:12b",
            "upgrade_keep_alive": "5m",
            "upgrade_probe_timeout": 2.0,
            "upgrade_probe_cache_seconds": 30.0,
        },
        NarratorConfig(),
    )
    assert cfg.upgrade_host == "http://desktop.local:11434"
    assert cfg.upgrade_model == "gemma3:12b"
    assert cfg.upgrade_keep_alive == "5m"
    assert cfg.upgrade_probe_timeout == 2.0
    assert cfg.upgrade_probe_cache_seconds == 30.0
