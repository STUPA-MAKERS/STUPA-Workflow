"""Corporate-design variants without a database (`app/modules/admin/cd_*`).

The tests cover four areas.

1. The upload policy `sniff_cd_logo`: SVG and PDF pass here, because these bytes
   only reach the LaTeX renderer. A mismatched magic byte is rejected.
2. The asset name that pytex sees: plain, unique per logo row and with the
   extension of the SNIFFED type.
3. `CdVariantService`: CRUD, the immutable key, the 409 on a delete while a
   Gremium still references the variant, and the storage error paths.
4. `resolve_cd_variant` for a vendored-only, an upload-only and a mixed variant.

The session fake follows `test_admin_service_cov`: `execute` and `scalars` share
one ordered queue, `scalar` and `get` have their own. Every audit write consumes
two `execute` results (the advisory lock and the `prev_hash` select).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

import pytest
from sqlalchemy import CheckConstraint, Table

from app.modules.admin.cd_logos import (
    ALLOWED_CD_LOGO_MIME,
    MAX_CD_LOGO_BYTES,
    VENDORED_LOGO_NAMES,
    asset_file_name,
    sniff_cd_logo,
)
from app.modules.admin.cd_resolver import cd_variant_key_for_gremium, resolve_cd_variant
from app.modules.admin.models import CdVariant, CdVariantLogo, Gremium
from app.modules.admin.schemas import (
    CdVariantCreate,
    CdVariantLogoReorder,
    CdVariantLogoVendoredCreate,
    CdVariantUpdate,
    GremiumCreate,
    GremiumUpdate,
)
from app.modules.admin.service import ConfigService
from app.modules.admin.service.cd_variants import CD_LOGO_PREFIX, CdVariantService
from app.modules.files.storage import StorageError
from app.shared.errors import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaTypeError,
    ValidationProblem,
)
from tests._support.files_fakes import FakeStorage

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 20
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
SVG_XML = b'<?xml version="1.0"?>\n<!-- a comment -->\n<svg viewBox="0 0 1 1"/>'
PDF = b"%PDF-1.7\n1 0 obj\n"
ICO = b"\x00\x00\x01\x00" + b"\x00" * 32


# --- fakes ----------------------------------------------------------------


class FakeResult:
    def __init__(self, items: Iterable[Any] = ()) -> None:
        self._items = list(items)

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any:
        return self._items[0] if self._items else None

    def scalar_one_or_none(self) -> Any:
        return self._items[0] if self._items else None


def res(*items: Any) -> FakeResult:
    return FakeResult(items)


def audit_results() -> list[FakeResult]:
    """The advisory lock plus the `prev_hash` select of one audit write."""
    return [res(), res()]


class FakeSession:
    """Stub for `AsyncSession`. `flush` stands in for `gen_random_uuid()`."""

    def __init__(
        self,
        results: Iterable[FakeResult] = (),
        *,
        scalars: Iterable[Any] = (),
        gets: Iterable[Any] = (),
    ) -> None:
        self._results = list(results)
        self._scalars = list(scalars)
        self._gets = list(gets)
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.flushed = 0
        self.committed = 0

    async def execute(self, _stmt: Any) -> FakeResult:
        return self._results.pop(0) if self._results else FakeResult()

    async def scalars(self, _stmt: Any) -> FakeResult:
        return self._results.pop(0) if self._results else FakeResult()

    async def scalar(self, _stmt: Any) -> Any:
        return self._scalars.pop(0) if self._scalars else None

    async def get(self, _model: Any, _ident: Any) -> Any:
        return self._gets.pop(0) if self._gets else None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        self.flushed += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def commit(self) -> None:
        self.committed += 1


def svc(
    results: Iterable[FakeResult] = (),
    *,
    scalars: Iterable[Any] = (),
    gets: Iterable[Any] = (),
    storage: Any = None,
) -> tuple[CdVariantService, FakeSession]:
    session = FakeSession(results, scalars=scalars, gets=gets)
    return CdVariantService(session, storage=storage), session  # type: ignore[arg-type]


def variant_row(**kw: Any) -> CdVariant:
    row = CdVariant(
        key=kw.pop("key", "stupa"),
        name=kw.pop("name", "StuPa"),
        base_variant=kw.pop("base_variant", "protocol"),
    )
    row.id = kw.pop("id", uuid.uuid4())
    for key, value in kw.items():
        setattr(row, key, value)
    return row


def gremium_row(**kw: Any) -> Gremium:
    """A `Gremium` with every column set. The server defaults only apply on insert."""
    row = Gremium(
        name=kw.pop("name", "StuPa"),
        slug=kw.pop("slug", "stupa"),
        cd_variant_id=kw.pop("cd_variant_id", None),
        default_lang="de",
        allow_vote_delegation=False,
        delegation_lead_minutes=0,
        delegation_allow_external=False,
        quorum_percent=None,
    )
    row.id = kw.pop("id", uuid.uuid4())
    return row


def logo_row(**kw: Any) -> CdVariantLogo:
    row = CdVariantLogo(
        variant_id=kw.pop("variant_id", uuid.uuid4()),
        slot=kw.pop("slot", "title"),
        position=kw.pop("position", 0),
        vendored_name=kw.pop("vendored_name", None),
        object_key=kw.pop("object_key", None),
        file_name=kw.pop("file_name", None),
        mime=kw.pop("mime", None),
        size=kw.pop("size", None),
    )
    row.id = kw.pop("id", uuid.uuid4())
    return row


# --- 1. upload policy -----------------------------------------------------


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (WEBP, "image/webp"),
        (SVG, "image/svg+xml"),
        (SVG_XML, "image/svg+xml"),
        (PDF, "application/pdf"),
    ],
)
def test_sniff_accepts_the_whole_allowlist(data: bytes, expected: str) -> None:
    """SVG and PDF pass here, unlike the site branding, and every hit is on the list."""
    assert sniff_cd_logo(data) == expected
    assert expected in ALLOWED_CD_LOGO_MIME


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"GIF89a" + b"\x00" * 16,  # a real image type, but not on the list
        ICO,  # branding accepts ICO, the CD logos do not
        b"not an image at all",
        b"<html><body>hi</body></html>",  # opens with '<' but is no SVG
        b"\x00\x01\x02\x03",
    ],
)
def test_sniff_rejects_a_mismatched_magic_byte(data: bytes) -> None:
    assert sniff_cd_logo(data) is None


def test_sniff_rejects_an_svg_hidden_behind_a_long_prologue() -> None:
    """The sniff reads a bounded head only, so a padded file cannot smuggle a root tag."""
    assert sniff_cd_logo(b"<" + b" " * 4096 + b"<svg/>") is None


def test_vendored_names_match_the_pytex_catalog() -> None:
    assert set(VENDORED_LOGO_NAMES) == {
        "HSRT",
        "INF",
        "ASTA",
        "STUPA",
        "ECHO",
        "MAKERS",
        "MAKERS-RAlign",
        "MAKERS-Icon",
        "Skyline",
    }


# --- 2. asset names -------------------------------------------------------


def test_asset_name_is_plain_unique_and_typed_by_the_sniffed_mime() -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    a = asset_file_name(first, "logo.png", "image/svg+xml")
    b = asset_file_name(second, "logo.png", "image/svg+xml")
    assert a != b  # two uploads of the same name never collide
    assert "/" not in a and "\\" not in a
    assert a.endswith(".svg")  # the extension follows the sniffed type, not the name


@pytest.mark.parametrize(
    ("name", "mime", "tail"),
    [
        ("../../etc/passwd", "image/png", "-passwd.png"),
        ("a b/c d.jpeg", "image/jpeg", "-c_d.jpg"),
        (None, "application/pdf", "-logo.pdf"),
        ("...", "image/webp", "-logo.webp"),
        ("x.png", "image/gif", "-x.bin"),  # unknown type falls back
    ],
)
def test_asset_name_sanitizes_the_original_name(name: str | None, mime: str, tail: str) -> None:
    logo_id = uuid.uuid4()
    assert asset_file_name(logo_id, name, mime) == f"{logo_id.hex}{tail}"


# --- 3. model constraints -------------------------------------------------


def _checks(model: type[Any]) -> dict[str, str]:
    """Map the CHECK constraint names of a model table to their SQL text."""
    table: Table = model.__table__
    return {
        str(c.name): str(c.sqltext)
        for c in table.constraints
        if isinstance(c, CheckConstraint)
    }


def test_logo_table_holds_the_exactly_one_of_constraint() -> None:
    """The database, not only the service, refuses a row with both or neither source."""
    checks = _checks(CdVariantLogo)
    assert checks["ck_cd_variant_logo_source"] == (
        "(vendored_name IS NULL) <> (object_key IS NULL)"
    )
    assert checks["ck_cd_variant_logo_slot"] == "slot IN ('title','footer')"


def test_variant_table_holds_the_base_variant_constraint() -> None:
    checks = _checks(CdVariant)
    assert checks["ck_cd_variant_base_variant"] == "base_variant IN ('report','protocol')"


# --- 4. service: variants -------------------------------------------------


async def test_create_variant_persists_and_audits() -> None:
    s, sess = svc([res(), *audit_results()])
    out = await s.create_variant(
        CdVariantCreate(key="senat", name="Senat", baseVariant="protocol"), "admin"
    )
    assert out.key == "senat" and out.base_variant == "protocol" and out.logos == []
    assert sess.committed == 1


async def test_create_variant_duplicate_key_conflicts() -> None:
    s, sess = svc([res(variant_row(key="stupa"))])
    with pytest.raises(ConflictError):
        await s.create_variant(CdVariantCreate(key="stupa", name="Zwei"), "admin")
    assert sess.committed == 0


async def test_update_variant_changes_name_and_base_variant() -> None:
    row = variant_row(key="stupa", name="StuPa", base_variant="protocol")
    s, sess = svc([*audit_results(), res()], gets=[row])
    out = await s.update_variant(
        row.id, CdVariantUpdate(name="StuPa neu", baseVariant="report"), "admin"
    )
    assert out.name == "StuPa neu" and out.base_variant == "report"
    assert sess.committed == 1


async def test_update_variant_keeps_the_key_immutable() -> None:
    """The key is the stable handle of the variant. A rename attempt gives 409."""
    row = variant_row(key="stupa")
    s, sess = svc(gets=[row])
    with pytest.raises(ConflictError, match="immutable"):
        await s.update_variant(row.id, CdVariantUpdate(key="asta"), "admin")
    assert row.key == "stupa" and sess.committed == 0


async def test_update_variant_accepts_the_unchanged_key() -> None:
    row = variant_row(key="stupa")
    s, _ = svc([*audit_results(), res()], gets=[row])
    out = await s.update_variant(row.id, CdVariantUpdate(key="stupa"), "admin")
    assert out.key == "stupa"


async def test_update_variant_unknown_id_404() -> None:
    s, _ = svc()
    with pytest.raises(NotFoundError):
        await s.update_variant(uuid.uuid4(), CdVariantUpdate(name="x"), "admin")


async def test_delete_variant_in_use_by_a_gremium_conflicts() -> None:
    """A referenced variant must not be deleted. The Gremium stays intact."""
    row = variant_row()
    s, sess = svc(gets=[row], scalars=[uuid.uuid4()])
    with pytest.raises(ConflictError, match="gremium"):
        await s.delete_variant(row.id, "admin")
    assert sess.deleted == [] and sess.committed == 0


async def test_delete_variant_drops_the_uploaded_objects() -> None:
    row = variant_row()
    logo = logo_row(variant_id=row.id, object_key="cd-logos/a/x.png", file_name="x.png")
    vendored = logo_row(variant_id=row.id, vendored_name="INF")
    storage = FakeStorage()
    storage.objects["cd-logos/a/x.png"] = (PNG, "image/png")
    s, sess = svc([res(logo, vendored), *audit_results()], gets=[row], storage=storage)
    await s.delete_variant(row.id, "admin")
    assert sess.deleted == [row] and sess.committed == 1
    assert storage.removed == ["cd-logos/a/x.png"]


async def test_list_variants_groups_the_logos_by_variant() -> None:
    first, second = variant_row(key="a"), variant_row(key="b")
    mine = logo_row(variant_id=first.id, vendored_name="INF")
    foreign = logo_row(variant_id=uuid.uuid4(), vendored_name="HSRT")
    s, _ = svc([res(first, second), res(mine, foreign)])
    out = await s.list_variants()
    assert [v.key for v in out] == ["a", "b"]
    assert [logo.vendored_name for logo in out[0].logos] == ["INF"]
    assert out[1].logos == []


async def test_list_variant_options_is_slim() -> None:
    s, _ = svc([res(variant_row(key="stupa", name="StuPa"))])
    out = await s.list_variant_options()
    assert [(o.key, o.name) for o in out] == [("stupa", "StuPa")]


# --- 5. service: logos ----------------------------------------------------


async def test_add_vendored_logo_appends_behind_the_last_position() -> None:
    row = variant_row()
    s, sess = svc([*audit_results()], gets=[row], scalars=[2])
    out = await s.add_vendored_logo(
        row.id, CdVariantLogoVendoredCreate(slot="footer", vendoredName="MAKERS-RAlign"), "a"
    )
    assert out.position == 3 and out.slot == "footer"
    assert out.vendored_name == "MAKERS-RAlign" and out.file_name is None
    assert sess.committed == 1


async def test_add_vendored_logo_starts_at_zero_in_an_empty_slot() -> None:
    row = variant_row()
    s, _ = svc([*audit_results()], gets=[row])
    out = await s.add_vendored_logo(
        row.id, CdVariantLogoVendoredCreate(slot="title", vendoredName="INF"), "a"
    )
    assert out.position == 0


async def test_add_vendored_logo_unknown_variant_404() -> None:
    s, _ = svc()
    with pytest.raises(NotFoundError):
        await s.add_vendored_logo(
            uuid.uuid4(), CdVariantLogoVendoredCreate(slot="title", vendoredName="INF"), "a"
        )


@pytest.mark.parametrize(("data", "mime"), [(SVG, "image/svg+xml"), (PDF, "application/pdf")])
async def test_upload_logo_accepts_svg_and_pdf(data: bytes, mime: str) -> None:
    """These bytes only reach LaTeX, never the browser, so the allowlist keeps them."""
    row = variant_row()
    storage = FakeStorage()
    s, sess = svc([*audit_results()], gets=[row], storage=storage)
    out = await s.upload_logo(row.id, data, slot="title", filename="logo.bin", actor="a")
    assert out.mime == mime and out.size == len(data)
    assert storage.put_calls[0].startswith(CD_LOGO_PREFIX)
    assert sess.committed == 1


async def test_upload_logo_rejects_a_mismatched_magic_byte() -> None:
    """The bytes decide, never the file name. `evil.png` that is HTML is refused."""
    row = variant_row()
    storage = FakeStorage()
    s, _ = svc(gets=[row], storage=storage)
    with pytest.raises(UnsupportedMediaTypeError):
        await s.upload_logo(
            row.id, b"<html>x</html>", slot="title", filename="evil.png", actor="a"
        )
    assert storage.put_calls == []


async def test_upload_logo_rejects_an_empty_file() -> None:
    s, _ = svc(gets=[variant_row()], storage=FakeStorage())
    with pytest.raises(UnsupportedMediaTypeError):
        await s.upload_logo(uuid.uuid4(), b"", slot="title", filename="a.png", actor="a")


async def test_upload_logo_rejects_oversize_bytes() -> None:
    s, _ = svc(gets=[variant_row()], storage=FakeStorage())
    with pytest.raises(PayloadTooLargeError):
        await s.upload_logo(
            uuid.uuid4(),
            PNG + b"\x00" * MAX_CD_LOGO_BYTES,
            slot="title",
            filename="a.png",
            actor="a",
        )


async def test_upload_logo_unknown_variant_404() -> None:
    s, _ = svc(storage=FakeStorage())
    with pytest.raises(NotFoundError):
        await s.upload_logo(uuid.uuid4(), PNG, slot="title", filename="a.png", actor="a")


async def test_upload_logo_without_storage_is_unavailable() -> None:
    s, _ = svc(gets=[variant_row()])
    with pytest.raises(ServiceUnavailableError):
        await s.upload_logo(uuid.uuid4(), PNG, slot="title", filename="a.png", actor="a")


async def test_upload_logo_storage_write_failure_is_unavailable() -> None:
    class Failing(FakeStorage):
        async def put(self, key: str, data: bytes, content_type: str) -> None:
            raise StorageError("boom")

    s, sess = svc(gets=[variant_row()], storage=Failing())
    with pytest.raises(ServiceUnavailableError):
        await s.upload_logo(uuid.uuid4(), PNG, slot="title", filename="a.png", actor="a")
    assert sess.committed == 0


async def test_logo_file_bytes_returns_the_object_and_name() -> None:
    logo = logo_row(object_key="cd-logos/a/x.svg", file_name="x.svg", mime="image/svg+xml")
    storage = FakeStorage()
    storage.objects["cd-logos/a/x.svg"] = (SVG, "image/svg+xml")
    s, _ = svc(gets=[logo], storage=storage)
    assert await s.logo_file_bytes(logo.id) == (SVG, "x.svg")


async def test_logo_file_bytes_for_a_vendored_entry_is_404() -> None:
    logo = logo_row(vendored_name="INF")
    s, _ = svc(gets=[logo], storage=FakeStorage())
    with pytest.raises(NotFoundError):
        await s.logo_file_bytes(logo.id)


async def test_logo_file_bytes_without_storage_is_unavailable() -> None:
    logo = logo_row(object_key="cd-logos/a/x.png", file_name="x.png")
    s, _ = svc(gets=[logo])
    with pytest.raises(ServiceUnavailableError):
        await s.logo_file_bytes(logo.id)


async def test_logo_file_bytes_storage_error_is_unavailable() -> None:
    class Failing(FakeStorage):
        async def get(self, key: str) -> bytes:
            raise StorageError("boom")

    logo = logo_row(object_key="cd-logos/a/x.png", file_name=None)
    s, _ = svc(gets=[logo], storage=Failing())
    with pytest.raises(ServiceUnavailableError):
        await s.logo_file_bytes(logo.id)


async def test_delete_logo_removes_the_object() -> None:
    logo = logo_row(object_key="cd-logos/a/x.png")
    storage = FakeStorage()
    storage.objects["cd-logos/a/x.png"] = (PNG, "image/png")
    s, sess = svc([*audit_results()], gets=[logo], storage=storage)
    await s.delete_logo(logo.id, "admin")
    assert sess.deleted == [logo] and storage.removed == ["cd-logos/a/x.png"]


async def test_delete_logo_survives_a_storage_outage() -> None:
    """The row is gone and committed. An orphan object must not turn the call red."""

    class Failing(FakeStorage):
        async def remove(self, key: str) -> None:
            raise StorageError("boom")

    logo = logo_row(object_key="cd-logos/a/x.png")
    s, sess = svc([*audit_results()], gets=[logo], storage=Failing())
    await s.delete_logo(logo.id, "admin")
    assert sess.committed == 1


async def test_delete_vendored_logo_touches_no_storage() -> None:
    logo = logo_row(vendored_name="INF")
    storage = FakeStorage()
    s, _ = svc([*audit_results()], gets=[logo], storage=storage)
    await s.delete_logo(logo.id, "admin")
    assert storage.removed == []


async def test_delete_logo_without_storage_still_drops_the_row() -> None:
    """Without MinIO (development, contract CI) the row goes and the object is skipped."""
    logo = logo_row(object_key="cd-logos/a/x.png")
    s, sess = svc([*audit_results()], gets=[logo])
    await s.delete_logo(logo.id, "admin")
    assert sess.deleted == [logo] and sess.committed == 1


async def test_delete_logo_unknown_id_404() -> None:
    s, _ = svc()
    with pytest.raises(NotFoundError):
        await s.delete_logo(uuid.uuid4(), "admin")


async def test_reorder_logos_sets_the_positions_of_one_slot() -> None:
    row = variant_row()
    first = logo_row(variant_id=row.id, slot="title", position=0, vendored_name="INF")
    second = logo_row(variant_id=row.id, slot="title", position=1, vendored_name="HSRT")
    other = logo_row(variant_id=row.id, slot="footer", position=0, vendored_name="ECHO")
    s, sess = svc([res(first, second, other), *audit_results()], gets=[row])
    out = await s.reorder_logos(
        row.id, CdVariantLogoReorder(slot="title", logoIds=[second.id, first.id]), "admin"
    )
    assert [logo.id for logo in out] == [second.id, first.id]
    assert (second.position, first.position) == (0, 1)
    assert other.position == 0 and sess.committed == 1


async def test_reorder_logos_rejects_an_incomplete_list() -> None:
    row = variant_row()
    first = logo_row(variant_id=row.id, slot="title", vendored_name="INF")
    second = logo_row(variant_id=row.id, slot="title", vendored_name="HSRT")
    s, sess = svc([res(first, second)], gets=[row])
    with pytest.raises(ValidationProblem):
        await s.reorder_logos(
            row.id, CdVariantLogoReorder(slot="title", logoIds=[first.id]), "admin"
        )
    assert sess.committed == 0


async def test_reorder_logos_rejects_a_foreign_id() -> None:
    row = variant_row()
    first = logo_row(variant_id=row.id, slot="title", vendored_name="INF")
    s, _ = svc([res(first)], gets=[row])
    with pytest.raises(ValidationProblem):
        await s.reorder_logos(
            row.id, CdVariantLogoReorder(slot="title", logoIds=[uuid.uuid4()]), "admin"
        )


async def test_reorder_logos_unknown_variant_404() -> None:
    s, _ = svc()
    with pytest.raises(NotFoundError):
        await s.reorder_logos(
            uuid.uuid4(), CdVariantLogoReorder(slot="title", logoIds=[]), "admin"
        )


# --- 6. gremium binding ---------------------------------------------------


async def test_create_gremium_rejects_an_unknown_cd_variant() -> None:
    """The id comes from the client, so the server checks it."""
    session = FakeSession([res()])
    service = ConfigService(session)  # type: ignore[arg-type]
    with pytest.raises(ValidationProblem):
        await service.create_gremium(
            GremiumCreate(name="X", slug="x", cdVariantId=uuid.uuid4()), "admin"
        )


async def test_update_gremium_rejects_an_unknown_cd_variant() -> None:
    row = gremium_row()
    session = FakeSession(gets=[row, None])
    service = ConfigService(session)  # type: ignore[arg-type]
    with pytest.raises(ValidationProblem):
        await service.update_gremium(
            row.id, GremiumUpdate(cdVariantId=uuid.uuid4()), "admin"
        )
    assert session.committed == 0


async def test_update_gremium_clears_the_cd_variant() -> None:
    """`cdVariantId: null` clears the binding. An absent field leaves it untouched."""
    variant = variant_row()
    row = gremium_row(cd_variant_id=variant.id)
    session = FakeSession([*audit_results()], gets=[row])
    service = ConfigService(session)  # type: ignore[arg-type]
    out = await service.update_gremium(row.id, GremiumUpdate(cdVariantId=None), "admin")
    assert out.cd_variant_id is None and row.cd_variant_id is None


async def test_update_gremium_binds_an_existing_cd_variant() -> None:
    variant = variant_row()
    row = gremium_row()
    session = FakeSession([*audit_results()], gets=[row, variant])
    service = ConfigService(session)  # type: ignore[arg-type]
    out = await service.update_gremium(
        row.id, GremiumUpdate(cdVariantId=variant.id), "admin"
    )
    assert out.cd_variant_id == variant.id


async def test_create_gremium_binds_an_existing_cd_variant() -> None:
    variant = variant_row()
    session = FakeSession([res(), *audit_results()], gets=[variant])
    service = ConfigService(session)  # type: ignore[arg-type]
    out = await service.create_gremium(
        GremiumCreate(name="StuPa", slug="stupa", cdVariantId=variant.id), "admin"
    )
    assert out.cd_variant_id == variant.id


async def test_cd_variant_key_reads_the_referenced_row() -> None:
    gremium = Gremium(name="StuPa", slug="stupa", cd_variant_id=uuid.uuid4())
    session = FakeSession(scalars=["stupa"])
    assert await cd_variant_key_for_gremium(session, gremium) == "stupa"  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "gremium", [None, Gremium(name="X", slug="x", cd_variant_id=None)]
)
async def test_cd_variant_key_without_a_variant_is_none(gremium: Gremium | None) -> None:
    session = FakeSession()
    assert await cd_variant_key_for_gremium(session, gremium) is None  # type: ignore[arg-type]


# --- 7. resolver ----------------------------------------------------------


def _resolver_session(
    variant: CdVariant, logos: list[CdVariantLogo]
) -> FakeSession:
    """`scalar` answers the gremium lookup, `get` the variant, `scalars` the logos."""
    return FakeSession([res(*logos)], scalars=[variant.id], gets=[variant])


async def test_resolve_vendored_only_variant_loads_no_asset() -> None:
    variant = variant_row(key="stupa", base_variant="protocol")
    logos = [
        logo_row(variant_id=variant.id, slot="title", vendored_name="STUPA"),
        logo_row(variant_id=variant.id, slot="footer", vendored_name="STUPA"),
    ]
    storage = FakeStorage()
    out = await resolve_cd_variant(
        _resolver_session(variant, logos), storage, uuid.uuid4()  # type: ignore[arg-type]
    )
    assert out is not None
    assert out.base_variant == "protocol"
    assert out.title_logos == ("STUPA",) and out.footer_logos == ("STUPA",)
    assert out.assets == {}


async def test_resolve_upload_only_variant_returns_names_and_bytes() -> None:
    variant = variant_row(key="custom", base_variant="report")
    logo = logo_row(
        variant_id=variant.id,
        slot="title",
        object_key="cd-logos/a/wappen.svg",
        file_name="wappen.svg",
        mime="image/svg+xml",
    )
    storage = FakeStorage()
    storage.objects["cd-logos/a/wappen.svg"] = (SVG, "image/svg+xml")
    out = await resolve_cd_variant(
        _resolver_session(variant, [logo]), storage, uuid.uuid4()  # type: ignore[arg-type]
    )
    assert out is not None
    name = asset_file_name(logo.id, "wappen.svg", "image/svg+xml")
    assert out.title_logos == (name,) and out.footer_logos == ()
    assert out.assets == {name: SVG}
    assert "/" not in name  # pytex refuses a path separator


async def test_resolve_mixed_variant_keeps_the_slot_order() -> None:
    variant = variant_row(key="mixed", base_variant="report")
    uploaded = logo_row(
        variant_id=variant.id,
        slot="title",
        position=0,
        object_key="cd-logos/a/mark.png",
        file_name="mark.png",
        mime="image/png",
    )
    vendored = logo_row(
        variant_id=variant.id, slot="title", position=1, vendored_name="MAKERS"
    )
    footer = logo_row(
        variant_id=variant.id, slot="footer", position=0, vendored_name="MAKERS-RAlign"
    )
    storage = FakeStorage()
    storage.objects["cd-logos/a/mark.png"] = (PNG, "image/png")
    out = await resolve_cd_variant(
        _resolver_session(variant, [uploaded, vendored, footer]),  # type: ignore[arg-type]
        storage,
        uuid.uuid4(),
    )
    assert out is not None
    name = asset_file_name(uploaded.id, "mark.png", "image/png")
    assert out.title_logos == (name, "MAKERS")
    assert out.footer_logos == ("MAKERS-RAlign",)
    assert out.assets == {name: PNG}


async def test_resolve_without_a_gremium_id_is_none() -> None:
    assert await resolve_cd_variant(FakeSession(), FakeStorage(), None) is None  # type: ignore[arg-type]


async def test_resolve_gremium_without_a_variant_is_none() -> None:
    session = FakeSession(scalars=[None])
    assert await resolve_cd_variant(session, FakeStorage(), uuid.uuid4()) is None  # type: ignore[arg-type]


async def test_resolve_unknown_base_variant_falls_back_to_report() -> None:
    variant = variant_row(key="x", base_variant="something-else")
    out = await resolve_cd_variant(
        _resolver_session(variant, []), FakeStorage(), uuid.uuid4()  # type: ignore[arg-type]
    )
    assert out is not None and out.base_variant == "report"


async def test_resolve_without_storage_fails_loudly() -> None:
    """A document with a silently missing logo is worse than a failed render."""
    variant = variant_row(key="custom")
    logo = logo_row(
        variant_id=variant.id, slot="title", object_key="cd-logos/a/x.png", mime="image/png"
    )
    with pytest.raises(ServiceUnavailableError):
        await resolve_cd_variant(
            _resolver_session(variant, [logo]), None, uuid.uuid4()  # type: ignore[arg-type]
        )


async def test_resolve_storage_error_is_unavailable() -> None:
    class Failing(FakeStorage):
        async def get(self, key: str) -> bytes:
            raise StorageError("boom")

    variant = variant_row(key="custom")
    logo = logo_row(
        variant_id=variant.id, slot="title", object_key="cd-logos/a/x.png", mime="image/png"
    )
    with pytest.raises(ServiceUnavailableError):
        await resolve_cd_variant(
            _resolver_session(variant, [logo]), Failing(), uuid.uuid4()  # type: ignore[arg-type]
        )
