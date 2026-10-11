"""Shared title-selection policies for CLI and GUI rip flows."""

from __future__ import annotations

from typing import Literal, get_args

TitleSelectionPolicy = Literal["all", "recommended", "primary"]
TITLE_SELECTION_POLICIES = get_args(TitleSelectionPolicy)


def select_title_indices(
    titles: list,
    analysis,
    policy: TitleSelectionPolicy,
) -> list[int]:
    """Return title indices selected by *policy* in physical disc order."""
    if policy not in TITLE_SELECTION_POLICIES:
        choices = ", ".join(TITLE_SELECTION_POLICIES)
        raise ValueError(f"unknown title-selection policy {policy!r}; choose {choices}")

    if policy == "all":
        selected = {title.index for title in titles}
    elif policy == "recommended":
        selected = {title.index for title in analysis.rippable_titles}
    else:
        selected = set(analysis.primary_title_indices)

    return [title.index for title in titles if title.index in selected]