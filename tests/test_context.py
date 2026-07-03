from __future__ import annotations

from beddington.context import describe_presence_scene
from beddington.grounding import has_unsupported_additions


def test_scene_radar_present() -> None:
    assert describe_presence_scene(True, True) == "active near the cot"
    assert describe_presence_scene(True, False) == "settled near the cot"
    assert describe_presence_scene(True, None) == "present near the cot"


def test_scene_radar_absent() -> None:
    assert (
        describe_presence_scene(False, True)
        == "movement elsewhere in the room, not at the cot"
    )
    assert (
        describe_presence_scene(False, False)
        == "quiet — no one detected near the cot or in the room"
    )
    assert describe_presence_scene(False, None) == "no one detected near the cot"


def test_scene_pir_only() -> None:
    assert describe_presence_scene(None, True) == "movement in the room"
    assert describe_presence_scene(None, False) == "room still"


def test_scene_none_when_nothing_reported() -> None:
    assert describe_presence_scene(None, None) is None
    # Non-bool values are ignored, not misread.
    assert describe_presence_scene("yes", 1) is None


def test_grounding_no_one_does_not_add_numeric_one() -> None:
    assert not has_unsupported_additions(
        "No one was detected in the room.",
        "Nobody was detected in the room.",
    )
    assert not has_unsupported_additions(
        "No-one was detected in the room.",
        "Nobody was detected in the room.",
    )


def test_grounding_large_number_does_not_crash() -> None:
    assert not has_unsupported_additions(
        "123456789012345678901234567890",
        "",
    )
