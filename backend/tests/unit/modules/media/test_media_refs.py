"""Unit tests of the canonical image reference helpers."""

from __future__ import annotations

from uuid import UUID

from app.modules.media.refs import image_ids_in, image_path, is_image_path

A = UUID("0b7c6f0e-3a51-4c3e-9b8e-6f1d2a3b4c5d")
B = UUID("1b7c6f0e-3a51-4c3e-9b8e-6f1d2a3b4c5d")


def test_image_path_round_trip() -> None:
    assert image_path(A) == f"/api/media/images/{A}"
    assert is_image_path(image_path(A))


def test_is_image_path_refuses_every_other_form() -> None:
    assert not is_image_path(f"/api/media/images/{str(A).upper()}")
    assert not is_image_path(f"/api/media/images/{A}/../x")
    assert not is_image_path(f"https://x.org/api/media/images/{A}")
    assert not is_image_path("/api/media/images/not-a-uuid")


def test_ids_in_order_of_first_appearance_without_duplicates() -> None:
    text = (
        f"![b](/api/media/images/{B}) text ![a](/api/media/images/{A})\n"
        f"![b again](/api/media/images/{B}) and ![a again](/api/media/images/{A})"
    )
    assert image_ids_in(text) == [B, A]


def test_ids_take_only_the_plain_form() -> None:
    text = (
        f'![t](/api/media/images/{A} "Titel") '
        f"![s](/api/media/images/{A} 'Titel') "
        f"![a](</api/media/images/{A}>) "
        f"![w]( /api/media/images/{A} )"
    )
    assert image_ids_in(text) == []


def test_ids_over_several_texts_and_none() -> None:
    texts = (None, f"![x](/api/media/images/{A})", "", f"[l](/api/media/images/{B})")
    assert image_ids_in(*texts) == [A, B]


def test_ids_ignore_other_destinations() -> None:
    text = (
        f"/api/media/images/{A} as plain text, "
        f"![x](https://evil.example/api/media/images/{A}), "
        f"![y](/api/media/images/{str(B).upper()})"
    )
    assert image_ids_in(text) == []
