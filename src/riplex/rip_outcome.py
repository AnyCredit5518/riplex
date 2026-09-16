"""Shared classification for a batch of rip results."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


class _RipResultLike(Protocol):
    success: bool


@dataclass(frozen=True)
class RipBatchOutcome:
    attempted: int
    succeeded: int

    @property
    def failed(self) -> int:
        return self.attempted - self.succeeded

    @property
    def has_successes(self) -> bool:
        return self.succeeded > 0

    @property
    def all_failed(self) -> bool:
        return self.attempted > 0 and self.succeeded == 0


def summarize_rip_results(
    results: Iterable[_RipResultLike],
) -> RipBatchOutcome:
    """Count successes and failures without imposing UI-specific behavior."""
    attempted = 0
    succeeded = 0
    for result in results:
        attempted += 1
        succeeded += int(result.success)
    return RipBatchOutcome(attempted=attempted, succeeded=succeeded)