"""Assessment context for the Stage 05 orchestrator.

Carries the Stage 03-validated target plus all shared limits in one
place, so tools never read conflicting hardcoded values. Includes an
overall deadline (monotonic clock) and a cancellation flag.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from config import config
from target import ValidatedTarget


@dataclass
class AssessmentContext:
    """Everything a bounded recon assessment needs, in one object."""

    target: ValidatedTarget
    request_timeout: float
    max_redirects: int
    max_response_size: int
    max_pages: int
    max_depth: int
    request_delay: float
    tool_timeout: float
    deadline: float  # time.monotonic() based
    _cancelled: bool = field(default=False, repr=False)

    @classmethod
    def create(cls, target: ValidatedTarget, overrides: dict | None = None) -> "AssessmentContext":
        """Build a context from project config, with optional overrides.

        Only known limit names are accepted; unknown keys are ignored
        (never trust caller-supplied names blindly).
        """
        recon = config.recon
        values = dict(
            request_timeout=recon.request_timeout,
            max_redirects=recon.max_redirects,
            max_response_size=recon.max_response_size,
            max_pages=recon.max_pages,
            max_depth=recon.max_depth,
            request_delay=recon.request_delay,
            tool_timeout=recon.tool_timeout,
            assessment_deadline=recon.assessment_deadline,
        )
        if overrides:
            for key, value in overrides.items():
                if key in values:
                    values[key] = value

        deadline = time.monotonic() + values.pop("assessment_deadline")
        return cls(target=target, deadline=deadline, **values)

    def time_remaining(self) -> float:
        """Seconds left before the overall deadline (never negative)."""
        return max(0.0, self.deadline - time.monotonic())

    @property
    def expired(self) -> bool:
        return self.time_remaining() <= 0.0

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled
