from __future__ import annotations

import subprocess
from pathlib import Path


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
