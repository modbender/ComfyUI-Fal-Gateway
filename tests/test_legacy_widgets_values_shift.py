"""Pins the algorithm behind the JS `repairLegacyWidgetsValuesShift` guard
in web/fal_gateway.js.

The JS guard runs at workflow-load time when a JsonExtractMany node has
a malformed `widgets_values` array (legacy save where the leading
`key_count` slot is missing → every value shifts up by one). This file
mirrors the guard's logic so we have a Python-level regression canary —
if anyone changes the rule in JS, this test should be updated in lockstep,
the test name + comments call that out.

We can't run the JS directly without a browser, but the algorithm is
small enough that a faithful port is cheaper than dragging in a JS test
runner.
"""

from __future__ import annotations

from typing import Any

MAX_JSON_EXTRACT_OUTPUTS = 10
JSON_EXTRACT_STATIC_WIDGET_COUNT = 3


def repair_legacy_widgets_values_shift(
    widgets_values: list[Any],
) -> tuple[list[Any], bool]:
    """Python mirror of web/fal_gateway.js::repairLegacyWidgetsValuesShift.

    Returns (corrected_array, was_repaired). The corrected array is a new
    list — caller decides whether to mutate in place.

    Detection: widgets_values[0] is a string AND not a positive-integer
    string. Repair: prepend a synthesized count (= len-1, clamped to
    [1, MAX_OUTPUTS]).
    """
    if not isinstance(widgets_values, list) or len(widgets_values) == 0:
        return widgets_values, False
    v0 = widgets_values[0]
    if isinstance(v0, (int, float)) and not isinstance(v0, bool):
        return widgets_values, False
    if isinstance(v0, str) and v0.strip().isdigit() and int(v0.strip()) >= 1:
        # Numeric string — JS coerces it in place but the array shape is fine.
        return [int(v0.strip()), *widgets_values[1:]], False
    inferred_count = max(1, min(MAX_JSON_EXTRACT_OUTPUTS, len(widgets_values) - 1))
    return [inferred_count, *widgets_values], True


def test_repair_recovers_the_3_entry_motion_prompt_case():
    """The exact shape we saw in production (3 broken nodes across
    Ferocine_LTX_I2V / Ferocine_Wan22_I2V / NullProtocol_Wan22_I2V): saved
    widgets_values = ['', 'motion_prompt', 'motion_negative_extras']."""
    broken = ["", "motion_prompt", "motion_negative_extras"]
    repaired, was_repaired = repair_legacy_widgets_values_shift(broken)
    assert was_repaired is True
    assert repaired == [2, "", "motion_prompt", "motion_negative_extras"]


def test_repair_leaves_well_formed_save_alone():
    """A correctly-saved widgets_values has the count as a number at [0].
    Guard must NOT trigger — false positives would corrupt good saves."""
    ok = [3, "", "title", "description", "tags"]
    repaired, was_repaired = repair_legacy_widgets_values_shift(ok)
    assert was_repaired is False
    assert repaired == ok  # unchanged


def test_repair_coerces_numeric_string_in_place_without_shifting():
    """If widgets_values[0] is a numeric string (e.g., '3' instead of 3),
    the array isn't misaligned — just int-coerce. No shift."""
    numeric_string = ["3", "", "title", "description", "tags"]
    repaired, was_repaired = repair_legacy_widgets_values_shift(numeric_string)
    assert was_repaired is False  # not a misalignment, just coercion
    assert repaired[0] == 3
    assert repaired[1:] == numeric_string[1:]


def test_repair_handles_2_entry_legacy_save():
    """Save format from an older era with just [default, key_1]. Recovery
    gives count=1 with key_1's value preserved."""
    legacy = ["default_val", "key_1_val"]
    repaired, was_repaired = repair_legacy_widgets_values_shift(legacy)
    assert was_repaired is True
    assert repaired == [1, "default_val", "key_1_val"]


def test_repair_clamps_inferred_count_to_max():
    """Pathological save with way more entries than MAX_OUTPUTS. The
    inferred count caps at MAX_OUTPUTS rather than going stratospheric."""
    huge = ["", *[f"key_{i}_val" for i in range(20)]]
    repaired, was_repaired = repair_legacy_widgets_values_shift(huge)
    assert was_repaired is True
    assert repaired[0] == MAX_JSON_EXTRACT_OUTPUTS
    # Rest of values preserved positionally.
    assert repaired[1:] == huge


def test_repair_handles_empty_array():
    """Edge case: empty widgets_values. No action, no crash."""
    empty: list[Any] = []
    repaired, was_repaired = repair_legacy_widgets_values_shift(empty)
    assert was_repaired is False
    assert repaired == []


def test_repair_handles_non_list_input():
    """Defensive: if widgets_values is somehow None or a non-list,
    guard returns the input unchanged."""
    repaired, was_repaired = repair_legacy_widgets_values_shift(None)  # type: ignore[arg-type]
    assert was_repaired is False
    assert repaired is None


def test_repair_is_idempotent_after_recovery():
    """Applying the guard twice in a row is a no-op on the second pass —
    once aligned, the array stays aligned."""
    broken = ["", "motion_prompt", "motion_negative_extras"]
    first_pass, repaired_1 = repair_legacy_widgets_values_shift(broken)
    second_pass, repaired_2 = repair_legacy_widgets_values_shift(first_pass)
    assert repaired_1 is True
    assert repaired_2 is False
    assert first_pass == second_pass
