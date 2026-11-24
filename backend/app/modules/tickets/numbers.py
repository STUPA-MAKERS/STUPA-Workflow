"""The number of a ticket: ``T-`` and eight random characters.

A number in sequence shows how many tickets the platform gets and lets a person guess
the number of a different ticket. The characters are the digits ``2`` to ``9`` and the
capital letters without ``I``, ``L`` and ``O``, because those look like ``0`` and ``1``.
The table stores the eight characters; the wire and the mails show them with ``T-``.
"""

from __future__ import annotations

import re
import secrets

#: The characters of a ticket number.
NUMBER_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
#: The count of random characters of a ticket number.
NUMBER_LENGTH = 8
#: ``T-7K3QX9MD``, ``t7k3qx9md`` and ``7K3QX9MD`` all name one ticket.
_FULL_RE = re.compile(rf"^(?:t-?)?([{NUMBER_ALPHABET}]{{{NUMBER_LENGTH}}})$", re.IGNORECASE)
#: A part of a number that a person types into the search, with or without ``T-``.
_PART_RE = re.compile(rf"^(?:t-)?([{NUMBER_ALPHABET}]{{1,{NUMBER_LENGTH}}})$", re.IGNORECASE)


def draw_number() -> str:
    """Draw the eight characters of a new number from a cryptographic random source."""
    return "".join(secrets.choice(NUMBER_ALPHABET) for _ in range(NUMBER_LENGTH))


def format_number(number: str) -> str:
    """Render a ticket number with its ``T-``."""
    return f"T-{number}"


def parse_number(text: str) -> str | None:
    """Return the stored form of a full number in ``text``, else None."""
    found = _FULL_RE.match(text.strip())
    return found.group(1).upper() if found is not None else None


def number_part(text: str) -> str | None:
    """Return the stored form of a part of a number in ``text``, else None."""
    found = _PART_RE.match(text.strip())
    return found.group(1).upper() if found is not None else None
