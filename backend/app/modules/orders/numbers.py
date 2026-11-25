"""The number of a Bestellung: ``B-`` and eight random characters (§F/finance/orders/002855).

The number is made like the number of a ticket: the digits ``2`` to ``9`` and the capital
letters without ``I``, ``L`` and ``O``, because those look like ``0`` and ``1``. A number in
sequence would show how many Bestellungen exist. The table stores the eight characters; the
wire shows them with ``B-``.
"""

from __future__ import annotations

import secrets

#: The characters of a number.
NUMBER_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
#: The count of random characters of a number.
NUMBER_LENGTH = 8


def draw_number() -> str:
    """Draw the eight characters of a new number from a cryptographic random source."""
    return "".join(secrets.choice(NUMBER_ALPHABET) for _ in range(NUMBER_LENGTH))


def format_number(number: str) -> str:
    """Render the number of a Bestellung with its ``B-``."""
    return f"B-{number}"
