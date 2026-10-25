"""The bundled builtin CD logos and their conversion into uploads.

The tests cover three areas.

1. The bundled files: one per vendored name, each equal to its pinned SHA-256,
   and equal to the submodule file when the submodule is checked out.
2. `builtin_logo_bytes`: an unknown name and a changed file.
3. `convert_builtin_cd_logos`: the lock, the conversion of every vendored row
   with the same slot and position, the rename of the seed name, one audit
   entry per variant, the idempotent second run and the storage errors.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from app.modules.admin import cd_builtin
from app.modules.admin.cd_builtin import (
    BUILTIN_LOGO_MIME,
    BUILTIN_LOGOS,
    BuiltinLogo,
    BuiltinLogoMismatchError,
    builtin_logo_bytes,
)
from app.modules.admin.cd_builtin.convert import BuiltinConversion, convert_builtin_cd_logos
from app.modules.admin.cd_logos import VENDORED_LOGO_NAMES, sniff_cd_logo
from app.modules.admin.service.cd_variants import CD_LOGO_PREFIX
from app.modules.audit.models import AuditEntry
from app.modules.files.storage import StorageError
from app.shared.errors import ServiceUnavailableError
from tests._support.files_fakes import FailingStorage, FakeStorage
from tests.unit.modules.admin.test_cd_variants import (
    FakeSession,
    audit_results,
    logo_row,
    res,
    variant_row,
)

_PACKAGE_DIR = Path(cd_builtin.__file__).parent
_SUBMODULE = Path(__file__).resolve().parents[5] / "typst" / "vendor" / "hsrtreport-typst" / "src"


def _submodule_path(name: str) -> Path:
    if name == "Skyline":
        return _SUBMODULE / "assets" / "images" / "Skyline.svg"
    return _SUBMODULE / "assets" / "images" / "logos" / f"{name}.svg"


def test_manifest_covers_every_vendored_name() -> None:
    assert set(BUILTIN_LOGOS) == set(VENDORED_LOGO_NAMES)
    assert {entry.file_name for entry in BUILTIN_LOGOS.values()} == {
        path.name for path in _PACKAGE_DIR.glob("*.svg")
    }


@pytest.mark.parametrize("name", VENDORED_LOGO_NAMES)
def test_bundled_file_matches_its_pinned_hash(name: str) -> None:
    """Match each bundled file to its pinned hash.

    The conversion stores the bytes as an SVG upload, so the sniff must agree.
    """
    entry = BUILTIN_LOGOS[name]
    data = (_PACKAGE_DIR / entry.file_name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry.sha256
    assert sniff_cd_logo(data) == BUILTIN_LOGO_MIME


@pytest.mark.parametrize("name", VENDORED_LOGO_NAMES)
def test_bundled_file_equals_the_submodule_copy(name: str) -> None:
    """The copy must not go stale. The test skips when the submodule is not checked out."""
    source = _submodule_path(name)
    if not source.is_file():
        pytest.skip("typst/vendor/hsrtreport-typst is not checked out")
    assert source.read_bytes() == (_PACKAGE_DIR / BUILTIN_LOGOS[name].file_name).read_bytes()


def test_builtin_logo_bytes_loads_and_checks() -> None:
    loaded = builtin_logo_bytes("STUPA")
    assert loaded is not None
    entry, data = loaded
    assert entry.file_name == "STUPA.svg" and len(data) > 0


def test_builtin_logo_bytes_unknown_name() -> None:
    assert builtin_logo_bytes("NOPE") is None


def test_builtin_logo_bytes_refuses_a_changed_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(BUILTIN_LOGOS, "INF", BuiltinLogo("INF.svg", "0" * 64))
    with pytest.raises(BuiltinLogoMismatchError):
        builtin_logo_bytes("INF")


def _session(
    rows: list[Any], seed_named: list[Any], audits: int, *, locked: bool = True
) -> FakeSession:
    results = [res(*rows), res(*seed_named)]
    for _ in range(audits):
        results.extend(audit_results())
    return FakeSession(results, scalars=[locked])


def _audits(session: FakeSession) -> list[AuditEntry]:
    return [obj for obj in session.added if isinstance(obj, AuditEntry)]


async def test_conversion_skips_when_another_runner_holds_the_lock() -> None:
    session = _session([], [], 0, locked=False)
    assert await convert_builtin_cd_logos(session, FakeStorage()) == BuiltinConversion(  # type: ignore[arg-type]
        skipped=True
    )
    assert session.committed == 0


async def test_conversion_without_work_changes_nothing() -> None:
    session = _session([], [], 0)
    storage = FakeStorage()
    assert await convert_builtin_cd_logos(session, storage) == BuiltinConversion()  # type: ignore[arg-type]
    assert storage.put_calls == [] and session.committed == 0


async def test_conversion_turns_vendored_rows_into_uploads() -> None:
    """Turn vendored rows into uploads; slot and position stay, so the PDF looks the same."""
    stupa = variant_row(key="stupa", name="StuPa")
    makers = variant_row(key="makers", name="MAKERS")
    title = logo_row(variant_id=stupa.id, slot="title", position=0, vendored_name="STUPA")
    footer = logo_row(variant_id=stupa.id, slot="footer", position=3, vendored_name="STUPA")
    icon = logo_row(variant_id=makers.id, slot="title", position=1, vendored_name="MAKERS-Icon")
    storage = FakeStorage()
    session = _session([title, footer, icon], [stupa], 2)

    result = await convert_builtin_cd_logos(session, storage)  # type: ignore[arg-type]

    assert result == BuiltinConversion(logos=3, variants=2, renamed=1)
    assert session.committed == 1
    for row, name in ((title, "STUPA"), (footer, "STUPA"), (icon, "MAKERS-Icon")):
        assert row.vendored_name is None
        assert row.file_name == f"{name}.svg"
        assert row.mime == "image/svg+xml"
        assert row.object_key is not None and row.object_key.startswith(CD_LOGO_PREFIX)
        assert row.object_key.endswith(f"/{name}.svg")
        stored, mime = storage.objects[row.object_key]
        assert mime == "image/svg+xml" and row.size == len(stored)
    assert (footer.slot, footer.position) == ("footer", 3)
    assert (icon.slot, icon.position) == ("title", 1)
    assert stupa.name == "STUPA" and makers.name == "MAKERS"

    audits = {entry.target_id: entry.data for entry in _audits(session)}
    assert set(audits) == {str(stupa.id), str(makers.id)}
    assert audits[str(stupa.id)]["renamed"] == {"old": "StuPa", "new": "STUPA"}
    assert [item["vendoredName"] for item in audits[str(stupa.id)]["convertedLogos"]] == [
        "STUPA",
        "STUPA",
    ]
    assert "renamed" not in audits[str(makers.id)]
    assert all(entry.actor == "system" for entry in _audits(session))


async def test_conversion_renames_a_variant_without_vendored_rows() -> None:
    stupa = variant_row(key="stupa", name="StuPa")
    session = _session([], [stupa], 1)
    result = await convert_builtin_cd_logos(session, None)  # type: ignore[arg-type]
    assert result == BuiltinConversion(logos=0, variants=1, renamed=1)
    assert stupa.name == "STUPA"
    (entry,) = _audits(session)
    assert "convertedLogos" not in entry.data


async def test_conversion_leaves_an_unknown_name_vendored() -> None:
    row = logo_row(slot="title", vendored_name="RETIRED")
    session = _session([row], [], 0)
    result = await convert_builtin_cd_logos(session, None)  # type: ignore[arg-type]
    assert result == BuiltinConversion()
    assert row.vendored_name == "RETIRED" and row.object_key is None
    assert session.committed == 1


async def test_conversion_needs_the_storage() -> None:
    row = logo_row(slot="title", vendored_name="INF")
    session = _session([row], [], 0)
    with pytest.raises(ServiceUnavailableError):
        await convert_builtin_cd_logos(session, None)  # type: ignore[arg-type]
    assert row.vendored_name == "INF" and session.committed == 0


async def test_conversion_does_not_commit_after_a_storage_error() -> None:
    row = logo_row(slot="title", vendored_name="INF")
    session = _session([row], [], 0)
    with pytest.raises(StorageError):
        await convert_builtin_cd_logos(session, FailingStorage())  # type: ignore[arg-type]
    assert session.committed == 0


async def test_second_run_finds_nothing_to_do() -> None:
    """Idempotent: the converted rows no longer match the vendored filter."""
    session = _session([], [], 0)
    assert (await convert_builtin_cd_logos(session, FakeStorage())).logos == 0  # type: ignore[arg-type]
