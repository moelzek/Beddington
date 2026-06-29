"""Beddington persona — a local LLM re-voices the deterministic assistant's
answers in character (a gentle bear in the spirit of Paddington), grounded so it
can never change a fact.

The deterministic brain (assistant.answer_question / summarise_night / the soothe
confirmations) computes the EXACT factual sentence. ``paddingtonise`` then asks a
local Ollama model to re-voice *that sentence* in character and VALIDATES the
result, falling back to the plain sentence on any failure. The model is never shown
raw sensor numbers and never decides what is true — it may only change wording.

Safety properties (fail-closed):
  * medically-sensitive answers (radar breathing/heart, the unsupported-vitals
    decline) are NEVER sent to the model — they are spoken verbatim;
  * every number is preserved (digit-run multiset), every unit is preserved, and
    no reassurance/medical word may be ADDED that was not already in the plain
    sentence; any violation -> speak the plain deterministic sentence;
  * the deterministic cry->alarm reflex (pipeline.run_pipeline) is unrelated and
    never imports this module.
"""

from __future__ import annotations

import json
import re
import urllib.request

from .config import NarratorConfig
from .narrator import _BANNED_NARRATION_WORDS

_SYSTEM_PROMPT = (
    "You are Beddington, a kindly little bear with the warm, polite, gentle manner of "
    "Paddington Bear, speaking aloud to a parent through a baby monitor in plain British "
    "English.\n"
    "You will be given ONE sentence of fact. Say the SAME fact back in your own gentle "
    "voice. This is a RE-WORDING task, not a conversation.\n"
    "You MUST:\n"
    '- include every number and unit exactly as given (for example "20 degrees Celsius" '
    'or "49 percent");\n'
    "- keep it to one short sentence;\n"
    '- add at most one small Paddington touch (marmalade, Aunt Lucy, or "if I may").\n'
    "You MUST NOT:\n"
    "- give any advice, suggestion or instruction;\n"
    "- add any new fact, cause, place or detail that is not in the sentence;\n"
    "- reassure the parent, or say the baby is safe, asleep, well, fine, calm, cosy, "
    "snug, peaceful or content;\n"
    "- make any medical comment.\n"
    "\n"
    "Example\n"
    "Fact: The room is about 21 degrees Celsius, a touch warm for a baby.\n"
    "You say: The room is about 21 degrees Celsius, a touch warm for a little one, if I may."
)

# Markers of a medically-sensitive answer (radar vitals readout / no-lock / the
# unsupported-vitals decline). These are spoken verbatim, never restyled.
_VITALS_MARKERS = (
    "from the radar",
    "breaths a minute",
    "beats per minute",
    "breathing and heart rate",
    "heart rate",
)

# Reassurance / medical words that must never be ADDED by the restyle. The plain
# answer legitimately contains some (e.g. "normal", "comfortable"), so the gate
# only rejects words the model introduces (delta check).
_REASSURANCE_WORDS = (
    "fine", "safe", "healthy", "normal", "normally", "okay", "ok", "asleep",
    "sleeping", "slept", "sleep", "well", "good", "stable", "calm", "settled",
    "peaceful", "peacefully", "soundly", "dozing", "slumbering", "slumber",
    "snug", "cosy", "cozy", "content", "contentedly", "resting", "serene",
    "tranquil",
)
_BANNED_WORDS = tuple(
    sorted(set(_BANNED_NARRATION_WORDS) | set(_REASSURANCE_WORDS))
)
_BANNED_PHRASES = (
    "breathing normally", "all good", "perfectly fine", "doing well",
    "nothing to worry", "don t worry", "at peace", "all is well",
    "sound asleep", "fast asleep", "resting peacefully", "no need to worry",
)

# Unit/keyword tokens whose set must be identical in plain vs candidate, so a
# number can't be re-attached to a different unit ("20 percent" -> "20 degrees").
_UNIT_WORDS = (
    "percent", "degrees", "celsius", "centimetres", "centimetre",
    "breaths", "beats", "hectopascals", "hectopascal",
)

_DIGITS = re.compile(r"\d+")

# Filler/function words ignored when checking that the restyle stayed on-topic.
_STOPWORDS = frozenset({
    "the", "that", "this", "there", "here", "with", "your", "you", "about",
    "just", "very", "quite", "rather", "right", "into", "from", "have", "they",
    "them", "then", "than", "what", "when", "your", "ever", "some", "only",
    "little", "ones", "dear", "parent", "please",
})


def _norm(text: str) -> str:
    """Lowercase, punctuation->spaces, space-padded — for whole-word/phrase tests."""
    return " " + re.sub(r"[^a-z0-9]+", " ", text.lower()).strip() + " "


def _digit_runs(text: str) -> list[str]:
    return _DIGITS.findall(text)


def _unit_set(text: str) -> set[str]:
    norm = _norm(text)
    return {word for word in _UNIT_WORDS if f" {word} " in norm}


def _content_words(text: str) -> set[str]:
    """Significant words (>= 4 letters, not filler) used to check the restyle
    actually conveys the same answer and isn't off-topic / meta text."""
    return {
        w for w in re.findall(r"[a-z]+", text.lower())
        if len(w) >= 4 and w not in _STOPWORDS
    }


def is_medically_sensitive(plain: str) -> bool:
    """True for radar-vitals / heart-rate answers, which are never restyled."""
    low = plain.lower()
    return any(marker in low for marker in _VITALS_MARKERS)


def _validate(candidate: str, plain: str) -> bool:
    """Fail-closed gate: candidate may differ from plain only in wording."""
    text = candidate.strip()
    if not text:
        return False
    if len(text) > len(plain) + 120:
        return False
    if text.count(".") + text.count("!") + text.count("?") > 3:
        return False
    # Numbers: exact multiset both ways (invented / dropped / altered / spelled-out).
    if sorted(_digit_runs(text)) != sorted(_digit_runs(plain)):
        return False
    # Units: no unit added, dropped, or swapped (closes the unit-swap hole).
    if _unit_set(text) != _unit_set(plain):
        return False
    # On-topic: the restyle must share most of the plain answer's content words,
    # so a small model can't pass with off-topic / meta text (e.g. echoing the
    # instructions) when there are no numbers to anchor on.
    plain_content = _content_words(plain)
    if plain_content:
        overlap = len(plain_content & _content_words(text))
        if overlap < (len(plain_content) + 1) // 2:
            return False
    # Banned words/phrases: only reject those the model ADDED (delta).
    cand_norm, plain_norm = _norm(candidate), _norm(plain)
    for word in _BANNED_WORDS:
        token = f" {word} "
        if token in cand_norm and token not in plain_norm:
            return False
    for phrase in _BANNED_PHRASES:
        token = f" {phrase} "
        if token in cand_norm and token not in plain_norm:
            return False
    return True


def _call_ollama(plain: str, config: NarratorConfig) -> str | None:
    """Ask the local model to re-voice ``plain``. Returns None on any failure."""
    payload = {
        "model": config.model,
        "prompt": _SYSTEM_PROMPT + "\n\nFact: " + plain + "\nYou say:",
        "stream": False,
        "options": {
            "num_predict": config.persona_num_predict,
            "temperature": config.persona_temperature,
        },
    }
    endpoint = config.host.rstrip("/") + "/api/generate"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "beddington/0.1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.persona_timeout) as response:
            result = json.load(response)
        text = str(result.get("response", "")).strip()
    except Exception:
        return None
    # Small models sometimes append a stray line after a blank line; keep the first.
    text = text.split("\n\n", 1)[0].strip()
    return text or None


def paddingtonise(plain_answer: str, config: NarratorConfig) -> str:
    """Re-voice ``plain_answer`` in character, or return it unchanged.

    Returns the plain answer verbatim when persona is off, the answer is
    medically sensitive (vitals), the model is unreachable, or the restyle fails
    validation — so the spoken content is never less accurate than the
    deterministic brain's.
    """
    plain = plain_answer or ""
    if not plain.strip():
        return plain_answer
    if not config.persona_enabled or config.backend != "ollama":
        return plain_answer
    if is_medically_sensitive(plain):
        return plain_answer
    candidate = _call_ollama(plain, config)
    if candidate is None:
        return plain_answer
    if _validate(candidate, plain):
        return candidate
    return plain_answer
