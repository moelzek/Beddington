from __future__ import annotations

import json
import urllib.error
import urllib.request

from .config import LlmConfig
from .models import NightReport


def polish_digest(summary: str, report: NightReport, config: LlmConfig) -> str:
    if not config.enabled:
        return summary
    if not config.base_url or not config.model or not config.api_key:
        raise ValueError(
            "LLM polish is enabled but LULLABY_LLM_BASE_URL, "
            "LULLABY_LLM_MODEL, or LULLABY_LLM_API_KEY is missing"
        )

    endpoint = config.base_url.rstrip("/") + "/chat/completions"
    event_text = [
        {
            "kind": event.kind,
            "offset_seconds": round(event.offset_seconds, 3),
            "duration_seconds": event.duration_seconds,
            "score": event.score,
        }
        for event in report.events
    ]
    payload = {
        "model": config.model,
        "temperature": 0.1,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Polish the supplied baby-monitor event summary into one short paragraph. "
                    "Preserve every number. Do not add causes, diagnoses, medical claims, "
                    "safety reassurance, or advice. Call uncertain interpretations best guesses."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"rule_based_summary": summary, "derived_events_only": event_text}
                ),
            },
        ],
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "lullaby/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM polish request failed: {exc}") from exc
    return str(result["choices"][0]["message"]["content"]).strip()
