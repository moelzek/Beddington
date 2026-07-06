from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pi_doctor.sh"

# Minimal stand-ins for the reporting helpers so extracted check functions
# can run standalone in a test harness.
HARNESS_PRELUDE = r'''
ok() { printf 'OK %s: %s\n' "$1" "$2"; }
warn() { printf 'WARN %s: %s\n' "$1" "$2"; }
fail() { printf 'FAIL %s: %s\n' "$1" "$2"; }
skip() { printf 'SKIP %s: %s\n' "$1" "$2"; }
have() { command -v "$1" >/dev/null 2>&1; }
'''


def _extract_function(name: str) -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(name)}\(\) \{{\n.*?^\}}$", text, re.MULTILINE | re.DOTALL
    )
    assert match, f"function {name} not found in pi_doctor.sh"
    return match.group(0)


def _run_harness(body: str, fake_bin: Path | None = None) -> str:
    env = dict(os.environ)
    if fake_bin is not None:
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
    result = subprocess.run(
        ["bash", "-c", HARNESS_PRELUDE + body],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout


def _fake_systemctl(tmp_path: Path, installed: list[str], active: list[str]) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    installed_case = " ".join(f"{u}.service" for u in installed) or "__none__"
    active_case = " ".join(active) or "__none__"
    systemctl = fake_bin / "systemctl"
    systemctl.write_text(
        f'''#!/usr/bin/env bash
cmd=$2
arg=${{3:-}}
case "$cmd" in
  list-unit-files)
    for unit in {installed_case}; do
      [[ "$arg" == "$unit" ]] && {{ echo "$unit enabled enabled"; exit 0; }}
    done
    exit 0
    ;;
  is-active)
    for unit in {active_case}; do
      [[ "$arg" == "$unit" ]] && {{ echo active; exit 0; }}
    done
    echo inactive
    exit 3
    ;;
esac
exit 0
''',
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    return fake_bin


def test_check_service_falls_back_to_legacy_unit(tmp_path: Path) -> None:
    fake_bin = _fake_systemctl(
        tmp_path, installed=["lullaby-liveview"], active=["lullaby-liveview"]
    )
    body = (
        _extract_function("check_service")
        + '\nSTATE=unknown\n'
        + 'check_service "liveview" STATE beddington-liveview lullaby-liveview\n'
        + 'printf "STATE=%s\\n" "$STATE"\n'
    )
    out = _run_harness(body, fake_bin)
    assert "OK service liveview: lullaby-liveview active" in out
    assert "STATE=active" in out


def test_check_service_prefers_canonical_unit_when_installed(tmp_path: Path) -> None:
    fake_bin = _fake_systemctl(
        tmp_path,
        installed=["beddington-assistant", "paddington"],
        active=["beddington-assistant"],
    )
    body = (
        _extract_function("check_service")
        + '\nSTATE=unknown\n'
        + 'check_service "assistant" STATE beddington-assistant paddington\n'
        + 'printf "STATE=%s\\n" "$STATE"\n'
    )
    out = _run_harness(body, fake_bin)
    assert "OK service assistant: beddington-assistant active" in out
    assert "STATE=active" in out


def test_check_service_skips_when_no_candidate_installed(tmp_path: Path) -> None:
    fake_bin = _fake_systemctl(tmp_path, installed=[], active=[])
    body = (
        _extract_function("check_service")
        + '\nSTATE=unknown\n'
        + 'check_service "assistant" STATE beddington-assistant paddington\n'
        + 'printf "STATE=%s\\n" "$STATE"\n'
    )
    out = _run_harness(body, fake_bin)
    assert "SKIP service assistant" in out
    assert "beddington-assistant paddington" in out
    assert "STATE=skip" in out


def test_check_log_recent_uses_first_existing_path(tmp_path: Path) -> None:
    legacy_log = tmp_path / "paddington.log"
    legacy_log.write_text("recent\n", encoding="utf-8")
    missing = tmp_path / "beddington-assistant.log"
    body = (
        _extract_function("mtime_epoch")
        + "\n"
        + _extract_function("check_log_recent")
        + f'\ncheck_log_recent "assistant" "active" "{missing}" "{legacy_log}"\n'
    )
    out = _run_harness(body)
    assert f"OK log assistant: {legacy_log} modified" in out


def _read_token(path: Path) -> str:
    script = r'''
TOKEN_FILE=$1
liveview_secret=$(<"$TOKEN_FILE")
liveview_secret="${liveview_secret%"${liveview_secret##*[![:space:]]}"}"
if [[ -z "$liveview_secret" ]]; then
  exit 3
fi
printf '%s' "$liveview_secret"
'''
    result = subprocess.run(
        ["bash", "-c", script, "bash", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_pi_doctor_token_read_accepts_file_without_newline(tmp_path: Path) -> None:
    token = tmp_path / "liveview-token"
    token.write_text("abc123secret", encoding="utf-8")

    assert _read_token(token) == "abc123secret"


def test_pi_doctor_token_read_rejects_whitespace_only(tmp_path: Path) -> None:
    token = tmp_path / "liveview-token"
    token.write_text(" \n\t\n", encoding="utf-8")

    result = subprocess.run(
        [
            "bash",
            "-c",
            r'''
TOKEN_FILE=$1
liveview_secret=$(<"$TOKEN_FILE")
liveview_secret="${liveview_secret%"${liveview_secret##*[![:space:]]}"}"
[[ -z "$liveview_secret" ]]
''',
            "bash",
            str(token),
        ],
        check=False,
    )
    assert result.returncode == 0
