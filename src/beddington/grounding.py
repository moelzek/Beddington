from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
import re

_NUMBER_RE = re.compile(r"~?\d+(?:\.\d+)?")
_WORD_RE = re.compile(r"[a-z]+")

_NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "once": "1",
    "two": "2",
    "twice": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
}

_UNIT_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "temperature": (
        re.compile(r"\b\d+(?:\.\d+)?\s*°?\s*c\b", re.IGNORECASE),
        re.compile(r"\bcelsius\b", re.IGNORECASE),
        re.compile(r"\bdegrees?\b", re.IGNORECASE),
    ),
    "percent": (
        re.compile(r"%"),
        re.compile(r"\bpercent(?:age)?\b", re.IGNORECASE),
    ),
    "duration": (
        re.compile(r"\bseconds?\b", re.IGNORECASE),
        re.compile(r"\bsecs?\b", re.IGNORECASE),
        re.compile(r"\bminutes?\b", re.IGNORECASE),
        re.compile(r"\bmins?\b", re.IGNORECASE),
        re.compile(r"\bhours?\b", re.IGNORECASE),
    ),
    "light": (
        re.compile(r"\blux\b", re.IGNORECASE),
        re.compile(r"\blx\b", re.IGNORECASE),
    ),
    "distance": (
        re.compile(r"\bcm\b", re.IGNORECASE),
        re.compile(r"\bcentimet(?:re|er)s?\b", re.IGNORECASE),
        re.compile(r"\bmet(?:re|er)s?\b", re.IGNORECASE),
        re.compile(r"\bmm\b", re.IGNORECASE),
    ),
    "heart_rate": (
        re.compile(r"\bbpm\b", re.IGNORECASE),
        re.compile(r"\bbeats?\s+(?:a|per)\s+minute\b", re.IGNORECASE),
    ),
    "respiratory_rate": (
        re.compile(r"\bbreaths?\s+(?:a|per)\s+minute\b", re.IGNORECASE),
        re.compile(r"\brespirations?\s+(?:a|per)\s+minute\b", re.IGNORECASE),
    ),
    "pressure": (
        re.compile(r"\bhpa\b", re.IGNORECASE),
        re.compile(r"\bhectopascals?\b", re.IGNORECASE),
        re.compile(r"\bohms?\b", re.IGNORECASE),
    ),
}

_CLAIM_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "temperature": (
        re.compile(r"\btemperatures?\b", re.IGNORECASE),
        re.compile(r"\bdegrees?\b", re.IGNORECASE),
        re.compile(r"\bcelsius\b", re.IGNORECASE),
        re.compile(r"\b\d+(?:\.\d+)?\s*°?\s*c\b", re.IGNORECASE),
        re.compile(r"\bwarm(?:er|th)?\b", re.IGNORECASE),
        re.compile(r"\bcool(?:er)?\b", re.IGNORECASE),
        re.compile(r"\bhot\b", re.IGNORECASE),
        re.compile(r"\bcold\b", re.IGNORECASE),
        re.compile(r"\bchilly\b", re.IGNORECASE),
    ),
    "humidity": (
        re.compile(r"\bhumid(?:ity)?\b", re.IGNORECASE),
        re.compile(r"\bdamp\b", re.IGNORECASE),
        re.compile(r"\bmoisture\b", re.IGNORECASE),
    ),
    "brightness": (
        re.compile(r"\bbrightness\b", re.IGNORECASE),
        re.compile(r"\billuminance\b", re.IGNORECASE),
        re.compile(r"\blighting\b", re.IGNORECASE),
        re.compile(r"\blux\b", re.IGNORECASE),
        re.compile(r"\blx\b", re.IGNORECASE),
    ),
    "presence": (
        re.compile(r"\bpresence\b", re.IGNORECASE),
        re.compile(r"\bpresent\b", re.IGNORECASE),
        re.compile(r"\bsomeone\b", re.IGNORECASE),
        re.compile(r"\bno\s+one\b", re.IGNORECASE),
        re.compile(r"\bnobody\b", re.IGNORECASE),
        re.compile(r"\bpersons?\b", re.IGNORECASE),
        re.compile(r"\bpeople\b", re.IGNORECASE),
        re.compile(r"\bnearby\b", re.IGNORECASE),
        re.compile(r"\broom\s+was\s+empty\b", re.IGNORECASE),
    ),
    "motion": (
        re.compile(r"\bmovement\b", re.IGNORECASE),
        re.compile(r"\bmotion\b", re.IGNORECASE),
        re.compile(r"\bmoving\b", re.IGNORECASE),
        re.compile(r"\bmoved\b", re.IGNORECASE),
        re.compile(r"\bstir(?:red|ring|s)?\b", re.IGNORECASE),
        re.compile(r"\brestless\b", re.IGNORECASE),
    ),
    "vitals": (
        re.compile(r"\bheart\b", re.IGNORECASE),
        re.compile(r"\bpulse\b", re.IGNORECASE),
        re.compile(r"\brespiratory\b", re.IGNORECASE),
        re.compile(r"\brespiration\b", re.IGNORECASE),
        re.compile(r"\bbreaths?\b", re.IGNORECASE),
        re.compile(r"\bbreathing\b", re.IGNORECASE),
        re.compile(r"\bvital(?:s| sign)?\b", re.IGNORECASE),
        re.compile(r"\bbpm\b", re.IGNORECASE),
        re.compile(r"\boxygen\b", re.IGNORECASE),
    ),
    "distance": (
        re.compile(r"\bdistance\b", re.IGNORECASE),
        re.compile(r"\btargets?\b", re.IGNORECASE),
        re.compile(r"\bcentimet(?:re|er)s?\b", re.IGNORECASE),
        re.compile(r"\bcm\b", re.IGNORECASE),
    ),
    "air": (
        re.compile(r"\bair\b", re.IGNORECASE),
        re.compile(r"\bgas\b", re.IGNORECASE),
        re.compile(r"\bvoc\b", re.IGNORECASE),
        re.compile(r"\bohms?\b", re.IGNORECASE),
        re.compile(r"\bpressure\b", re.IGNORECASE),
    ),
}


def has_unsupported_additions(candidate: str, source: str) -> bool:
    """True when ``candidate`` adds grounded-sensitive facts absent from ``source``."""
    candidate_numbers = _number_values(candidate)
    source_numbers = _number_values(source)
    if candidate_numbers - source_numbers:
        return True

    candidate_units = _matched_categories(candidate, _UNIT_PATTERNS)
    source_units = _matched_categories(source, _UNIT_PATTERNS)
    if not candidate_units <= source_units:
        return True

    candidate_claims = _matched_categories(candidate, _CLAIM_PATTERNS)
    source_claims = _matched_categories(source, _CLAIM_PATTERNS)
    return not candidate_claims <= source_claims


def _number_values(text: str) -> Counter[str]:
    values: Counter[str] = Counter()
    for match in _NUMBER_RE.findall(text):
        value = _normalise_number(match)
        if value is not None:
            values[value] += 1
    words = _WORD_RE.findall(text.lower())
    for index, word in enumerate(words):
        if word == "one" and index > 0 and words[index - 1] == "little":
            continue
        value = _NUMBER_WORDS.get(word)
        if value is not None:
            values[value] += 1
    return values


def _normalise_number(value: str) -> str | None:
    try:
        decimal = Decimal(value.lstrip("~"))
    except InvalidOperation:
        return None
    normalised = decimal.normalize()
    if normalised == normalised.to_integral():
        return str(normalised.quantize(Decimal(1)))
    return format(normalised, "f")


def _matched_categories(
    text: str,
    patterns: dict[str, tuple[re.Pattern[str], ...]],
) -> set[str]:
    return {
        category
        for category, options in patterns.items()
        if any(pattern.search(text) for pattern in options)
    }
