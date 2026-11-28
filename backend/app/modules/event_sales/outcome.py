"""The result of a run: the new bookings and each failure with its cause (003104)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Integration = Literal["pretix", "mollie"]


@dataclass(frozen=True, slots=True)
class Failure:
    """One failed read or booking.

    Attributes:
        integration: `pretix` or `mollie`.
        source: What failed: `read`, `order`, `refund`, `payment`, `chargeback` or
            `settlement`.
        key: The pretix event, the code of the order or the id of Mollie.
        cause: The short cause code, never a text of an exception.
    """

    integration: Integration
    source: str
    key: str
    cause: str


@dataclass(frozen=True, slots=True)
class Outcome:
    """The new bookings of a run and its failures."""

    booked: int = 0
    failures: tuple[Failure, ...] = ()

    def __add__(self, other: Outcome) -> Outcome:
        """Join the results of two parts of a run."""
        return Outcome(self.booked + other.booked, self.failures + other.failures)


def joined(parts: list[Outcome]) -> Outcome:
    """Join the results of every part of a run."""
    return sum(parts, Outcome())
