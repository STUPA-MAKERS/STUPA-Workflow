"""Protokoll-Service (T-22, api.md »protocol«, flows §7).

An eine ``AsyncSession`` gebundener Service für den Protokoll-Lebenszyklus:

* :meth:`get_or_create` — Protokoll einer Sitzung anlegen **oder** laden (idempotent
  über UNIQUE ``meeting_id``); übernimmt ``gremium_id``/``cd_variant`` von Sitzung+Gremium.
* :meth:`update_markdown` — Editor-Body aktualisieren (nur im Entwurf).
* :meth:`embed_votes` — Abstimmungen als Markdown-Snippets anhängen + ``protocol_vote_ref``
  schreiben (idempotent: schon referenzierte Votes werden übersprungen).
* :meth:`finalize` — Markdown → pytex → PDF → MinIO → Mail an
  MAIL_LIST(gremium); ``status='final'`` + ``sent_at``.

**Wiederverwendung T-20** (keine Duplikation): pytex-Client, Object-Storage
und die Mail-Queue/-``MailMessage`` stammen unverändert aus
:mod:`app.modules.pdf` / :mod:`app.modules.notifications`. Der Render läuft hier
**synchron** im Request (das FE T-33 erwartet ``ProtocolOut`` mit ``pdfUrl`` direkt
aus der ``finalize``-Antwort, nicht den 202-Job-Pfad).

**Fail-Disziplin** (security.md §2): ist Storage bewusst »aus« (DEV/Demo ohne MinIO),
wird ``finalize`` trotzdem abgeschlossen (``status='final'`` + Mail ohne PDF-Link).
Schlägt ein **vorhandenes** Render-/Storage-Backend transient fehl, wirft der Service
:class:`ServiceUnavailableError` (503) → die Session-Dependency rollt zurück, das
Protokoll bleibt Entwurf und der Aufruf ist wiederholbar.
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import time as _time
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Gremium, GremiumMembership, MailList
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.files.storage import ObjectStorage, StorageError
from app.modules.livevote.models import Meeting, MeetingAgendaItem, MeetingAttendance
from app.modules.notifications.layout import (
    reason_text,
    render_layout,
    text_to_html,
)
from app.modules.notifications.mail import (
    MailAttachment,
    MailMessage,
    compute_idempotency_key,
)
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.recipients import RecipientResolver
from app.modules.notifications.service import filter_recipients_by_preference
from app.modules.pdf.pytex_client import PytexClient, PytexError
from app.modules.protocol.markdown import (
    ProtocolDoc,
    build_protocol_document,
    build_vote_snippet,
    demote_headings,
    protocol_variant_for,
)
from app.modules.protocol.models import Protocol, ProtocolVoteRef
from app.modules.protocol.schemas import ProtocolOut
from app.modules.voting.models import Vote
from app.modules.voting.service import VotingService
from app.settings import Settings, get_settings
from app.shared.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
)


def protocol_storage_key(protocol_id: UUID) -> str:
    """Deterministischer MinIO-Key (eigener ``pdf/protocol/``-Präfix, T-20-Schema)."""
    return f"pdf/protocol/{protocol_id}.pdf"


def protocol_public_storage_key(protocol_id: UUID) -> str:
    """MinIO-Key der redigierten öffentlichen Protokoll-Variante (#PII-Re-Add)."""
    return f"pdf/protocol/{protocol_id}-public.pdf"


# Platzhalter für den Body nicht-öffentlicher TOPs im öffentlichen PDF (Nummerierung
# bleibt erhalten, der Inhalt wird redigiert).
_NON_PUBLIC_PLACEHOLDER = "*(nicht-öffentlicher Tagesordnungspunkt)*"


class ProtocolService:
    """Protokoll-Operationen + (synchrone) Finalisierung über die T-20-Infrastruktur."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        storage: ObjectStorage | None = None,
        pytex: PytexClient | None = None,
        mail_queue: MailQueue | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.storage = storage
        self.pytex = pytex
        self.mail_queue = mail_queue
        self.settings = settings

    # ----------------------------------------------------------------- helpers
    async def _get(self, protocol_id: UUID) -> Protocol:
        protocol = (
            await self.session.execute(
                select(Protocol).where(Protocol.id == protocol_id)
            )
        ).scalar_one_or_none()
        if protocol is None:
            raise NotFoundError(f"protocol {protocol_id} not found")
        return protocol

    def _pdf_path(self, protocol: Protocol) -> str | None:
        """App-relativer PDF-Pfad (über nginx /api/ erreichbar, nie ein Bucket-Link).

        MinIO liegt im ``internal``-Netz ohne Port-Publish; eine S3v4-signierte URL
        bindet den (internen) Host in die Signatur → vom Browser unerreichbar. Statt
        dessen streamt der ``/pdf``-Endpunkt die Bytes server-seitig aus dem Storage."""
        if protocol.pdf_storage_key is not None and self.storage is not None:
            return f"/api/protocols/{protocol.id}/pdf"
        return None

    def _public_pdf_path(self, protocol: Protocol) -> str | None:
        """App-relativer Pfad der redigierten öffentlichen Variante (#PII-Re-Add)."""
        if protocol.public_pdf_storage_key is not None and self.storage is not None:
            return f"/api/protocols/{protocol.id}/pdf/public"
        return None

    async def get_pdf_bytes(self, protocol_id: UUID) -> bytes:
        """PDF-Bytes des Protokolls aus dem Storage holen (für den ``/pdf``-Stream).

        404, wenn das Protokoll fehlt, noch kein PDF gerendert wurde oder Storage »aus«
        ist. Transiente Storage-Fehler → 503 (wiederholbar)."""
        protocol = await self._get(protocol_id)
        if protocol.pdf_storage_key is None or self.storage is None:
            raise NotFoundError(f"protocol {protocol_id} has no PDF")
        try:
            return await self.storage.get(protocol.pdf_storage_key)
        except StorageError as exc:
            raise ServiceUnavailableError(
                "Protocol PDF temporarily unavailable."
            ) from exc

    async def get_public_pdf_bytes(self, protocol_id: UUID) -> bytes:
        """Bytes der redigierten öffentlichen Variante (für den ``/pdf/public``-Stream)."""
        protocol = await self._get(protocol_id)
        if protocol.public_pdf_storage_key is None or self.storage is None:
            raise NotFoundError(f"protocol {protocol_id} has no public PDF")
        try:
            return await self.storage.get(protocol.public_pdf_storage_key)
        except StorageError as exc:
            raise ServiceUnavailableError(
                "Protocol PDF temporarily unavailable."
            ) from exc

    def _to_out(self, protocol: Protocol) -> ProtocolOut:
        return ProtocolOut(
            id=protocol.id,
            meetingId=protocol.meeting_id,
            markdown=protocol.markdown,
            status=protocol.status,  # type: ignore[arg-type]
            pdfUrl=self._pdf_path(protocol),
            publicPdfUrl=self._public_pdf_path(protocol),
            sentAt=protocol.sent_at,
        )

    # ------------------------------------------------------------- get/create
    async def _by_meeting(self, meeting_id: UUID) -> Protocol | None:
        return (
            await self.session.execute(
                select(Protocol).where(Protocol.meeting_id == meeting_id)
            )
        ).scalar_one_or_none()

    @staticmethod
    def _insert_values(
        meeting: Meeting, gremium: Gremium | None, author: str | None
    ) -> dict[str, object]:
        """Spalten-Werte einer frischen ``protocol``-Zeile (``cd_variant`` vom Gremium)."""
        return {
            "meeting_id": meeting.id,
            "gremium_id": meeting.gremium_id,
            "markdown": "",
            "status": "draft",
            "author": author,
            "cd_variant": gremium.cd_variant if gremium is not None else None,
        }

    async def get_by_meeting(self, meeting_id: UUID) -> ProtocolOut:
        """Protokoll der Sitzung **lesen** (404 ohne Protokoll) — Reload-/Poll-Pfad.

        Bewusst ohne Anlage-Seiteneffekt: das FE pollt während des Hintergrund-
        Renders; ein GET unterliegt nicht dem Default-Write-Rate-Limit (#429)."""
        protocol = await self._by_meeting(meeting_id)
        if protocol is None:
            raise NotFoundError(f"protocol for meeting {meeting_id} not found")
        return self._to_out(protocol)

    async def get_or_create(
        self, meeting_id: UUID, *, author: str | None = None
    ) -> ProtocolOut:
        """Protokoll der Sitzung anlegen **oder** laden (idempotent). 404 ohne Sitzung.

        Race-sicher: bei parallelem POST verhindert ``INSERT … ON CONFLICT
        (meeting_id) DO NOTHING`` die UNIQUE-Verletzung (kein ``IntegrityError`` → kein
        500); das anschließende Re-Select liefert in **beiden** Fällen (selbst angelegt
        **oder** vom Parallel-Request gewonnen) dieselbe Zeile zurück (idempotent)."""
        existing = await self._by_meeting(meeting_id)
        if existing is not None:
            return self._to_out(existing)

        meeting = await self.session.get(Meeting, meeting_id)
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        # Das Protokoll entsteht ausschließlich beim Start der Sitzung (planned→live),
        # nie manuell vorab: vor dem Start kann nicht protokolliert werden.
        if meeting.status == "planned":
            raise ConflictError(
                "the meeting has not started — its minutes are created on start"
            )
        gremium = await self.session.get(Gremium, meeting.gremium_id)
        await self.session.execute(
            pg_insert(Protocol)
            .values(**self._insert_values(meeting, gremium, author))
            .on_conflict_do_nothing(constraint="uq_protocol_meeting")
        )
        await self.session.commit()

        protocol = await self._by_meeting(meeting_id)
        if protocol is None:  # nur falls die Zeile zwischen Insert+Select verschwand
            raise NotFoundError(f"protocol for meeting {meeting_id} not found")
        return self._to_out(protocol)

    # --------------------------------------------------------------- markdown
    async def update_markdown(self, protocol_id: UUID, markdown: str) -> ProtocolOut:
        """Editor-Body aktualisieren. 409, wenn das Protokoll bereits final ist."""
        protocol = await self._get(protocol_id)
        self._ensure_draft(protocol)
        protocol.markdown = markdown
        await self.session.flush()
        await self.session.commit()
        return self._to_out(protocol)

    # ----------------------------------------------------------------- votes
    async def embed_votes(
        self, protocol_id: UUID, vote_ids: list[UUID]
    ) -> ProtocolOut:
        """Abstimmungen als Snippets anhängen + ``protocol_vote_ref`` (idempotent)."""
        protocol = await self._get(protocol_id)
        self._ensure_draft(protocol)
        already = set(
            (
                await self.session.execute(
                    select(ProtocolVoteRef.vote_id).where(
                        ProtocolVoteRef.protocol_id == protocol_id
                    )
                )
            )
            .scalars()
            .all()
        )
        voting = VotingService(self.session)
        snippets: list[str] = []
        for vote_id in vote_ids:
            if vote_id in already:
                continue  # schon eingebettet → kein Doppel-Snippet
            await self._get_vote(vote_id)  # 404 + verhindert FK-IntegrityError beim Insert
            already.add(vote_id)
            # Race-sicher: ON CONFLICT (protocol_id, vote_id) DO NOTHING. Schreibt ein
            # Parallel-Request den Ref zuerst, liefert RETURNING nichts → kein Doppel-
            # Snippet (idempotent, kein IntegrityError/500).
            inserted = (
                await self.session.execute(
                    pg_insert(ProtocolVoteRef)
                    .values(protocol_id=protocol_id, vote_id=vote_id)
                    .on_conflict_do_nothing(constraint="uq_protocol_vote_ref")
                    .returning(ProtocolVoteRef.id)
                )
            ).first()
            if inserted is None:
                continue  # nebenläufig bereits eingebettet
            view = await voting.get(vote_id)
            snippets.append(
                build_vote_snippet(
                    _vote_title(view.application_id, view.question),
                    view.tally.counts,
                    question=view.question,
                )
            )

        if snippets:
            body = protocol.markdown.rstrip("\n")
            joined = "\n\n".join(snippets)
            protocol.markdown = f"{body}\n\n{joined}\n" if body else f"{joined}\n"
            await self.session.flush()
        await self.session.commit()
        return self._to_out(protocol)

    # -------------------------------------------------------------- finalize
    async def start_finalize(self, protocol_id: UUID) -> tuple[ProtocolOut, bool]:
        """Finalisierung anstoßen: ``draft → rendering`` (committed, nicht-blockierend).

        Der Aufrufer (Router) enqueued anschließend den ``render_protocol``-Worker-Job.
        Idempotent: ein bereits ``rendering``/``final`` Protokoll wird unverändert
        zurückgegeben — das zweite Tupel-Element ``False`` heißt »nichts enqueuen«
        (kein Doppel-Render, kein Doppelversand)."""
        protocol = await self._get(protocol_id)
        if protocol.status in ("rendering", "final"):
            return self._to_out(protocol), False
        protocol.status = "rendering"
        await self.session.flush()
        await self.session.commit()
        return self._to_out(protocol), True

    async def revert_to_draft(self, protocol_id: UUID) -> None:
        """``rendering → draft`` nach dauerhaftem Render-/Versand-Fehler.

        Das Protokoll bleibt damit re-finalisierbar und hängt **nie** in
        ``rendering`` fest; ein bereits finales Protokoll bleibt unangetastet."""
        protocol = await self._get(protocol_id)
        if protocol.status == "rendering":
            protocol.status = "draft"
            await self.session.flush()
            await self.session.commit()

    async def finalize(self, protocol_id: UUID, *, now: datetime) -> ProtocolOut:
        """Markdown → PDF → MinIO → Mail an MAIL_LIST(gremium); ``final``.

        Läuft im Worker (``render_protocol``, Status ``rendering``) **oder** synchron
        als Fallback ohne Redis (Status noch ``draft``). Idempotent: ein bereits
        finalisiertes Protokoll wird unverändert (mit frisch signierter URL)
        zurückgegeben — kein zweiter Render, kein Doppelversand."""
        protocol = await self._get(protocol_id)
        if protocol.status == "final":
            return self._to_out(protocol)

        # Render (pytex) läuft VOR dem Commit: ein dauerhafter Compile-Fehler (4xx)
        # bzw. ein transienter pytex-Ausfall (5xx) rollt die Session zurück, das
        # Protokoll bleibt Entwurf. Der Storage-``put`` und der Mail-Enqueue erfolgen
        # aber bewusst ERST NACH erfolgreichem Commit (#pre-commit-side-effects):
        # scheitert der Commit, gäbe es sonst ein verwaistes MinIO-Objekt und einen
        # bereits eingereihten Versand-Job zu einer Zeile, die nie ``final`` wurde.
        # ``_render_pdf`` setzt nur die Key-Spalten + liefert die Bytes; der Upload
        # geschieht in ``_store`` post-commit.
        uploads: list[tuple[str, bytes]] = []
        if await self._has_non_public(protocol.meeting_id):
            # Dual-Render: vollständiges internes PDF + redigiertes öffentliches PDF.
            # Per Mail geht NUR die öffentliche Variante (nicht-öffentliche TOPs sollen
            # nicht im Verteiler landen).
            internal_md = await self._build_document(protocol, public=False)
            internal_pdf = await self._render_pdf(protocol, internal_md, public=False)
            public_md = await self._build_document(protocol, public=True)
            public_pdf = await self._render_pdf(protocol, public_md, public=True)
            if internal_pdf is not None:
                uploads.append((protocol_storage_key(protocol.id), internal_pdf))
            if public_pdf is not None:
                uploads.append((protocol_public_storage_key(protocol.id), public_pdf))
            mail_pdf = public_pdf
        else:
            markdown = await self._build_document(protocol)
            mail_pdf = await self._render_pdf(protocol, markdown)
            if mail_pdf is not None:
                uploads.append((protocol_storage_key(protocol.id), mail_pdf))
        protocol.status = "final"
        protocol.sent_at = now
        await self.session.flush()
        await self.session.commit()
        # Ab hier ist der DB-Stand persistent — Seiteneffekte sind jetzt sicher.
        await self._store(uploads)
        await self._send(protocol, mail_pdf)
        return self._to_out(protocol)

    # ----------------------------------------------------------- finalize bits
    async def _build_document(self, protocol: Protocol, *, public: bool = False) -> str:
        meeting = await self.session.get(Meeting, protocol.meeting_id)
        gremium = await self.session.get(Gremium, protocol.gremium_id)
        title = meeting.title if meeting is not None else "Protokoll"
        # Quelle der Wahrheit ist der pro-TOP-Editor (Tagesordnung). Existieren TOPs,
        # wird das Protokoll aus ihren Markdown-Bodies + Beschluss-Snippets montiert;
        # andernfalls Fallback auf das frei editierte ``protocol.markdown`` (Bestand).
        # ``public=True`` redigiert nicht-öffentliche TOPs (#PII-Re-Add).
        assembled = await self._assemble_from_agenda(protocol.meeting_id, public=public)
        protokollant, present, absent = await self._header_meta(meeting)
        return build_protocol_document(
            ProtocolDoc(
                title=title,
                gremium_name=getattr(gremium, "name", None) if gremium is not None else None,
                cd_variant=protocol.cd_variant,
                date=meeting.date if meeting is not None else None,
                start_time=getattr(meeting, "start_time", None) if meeting is not None else None,
                end_time=self._local_end_time(
                    getattr(meeting, "closed_at", None) if meeting is not None else None
                ),
                protokollant=protokollant,
                present=present,
                absent=absent,
                quorate=await self._quorate(gremium, len(present)),
                markdown=assembled or protocol.markdown,
            )
        )

    def _local_end_time(self, closed_at: object) -> _time | None:
        """``meeting.closed_at`` (UTC) → lokale Uhrzeit für die »Ende«-Zeile (#14)."""
        if not isinstance(closed_at, datetime):
            return None
        settings = self.settings or get_settings()
        tz = ZoneInfo(settings.local_timezone)
        return closed_at.astimezone(tz).time().replace(second=0, microsecond=0)

    async def _quorate(self, gremium: object | None, present_count: int) -> bool | None:
        """Beschlussfähigkeit: Anwesende vs. aktive Mitglieder (#protocol-quorum).

        Schwelle = ``gremium.quorum_percent`` (falls gesetzt), sonst »mehr als die
        Hälfte«. ``None`` ohne Gremium/Mitglieder — dann keine Aussage im PDF."""
        gremium_id = getattr(gremium, "id", None)
        if gremium_id is None:
            return None
        now = datetime.now(UTC)
        members = (
            await self.session.scalar(
                select(func.count(func.distinct(GremiumMembership.principal_id))).where(
                    GremiumMembership.gremium_id == gremium_id,
                    (GremiumMembership.valid_from.is_(None))
                    | (GremiumMembership.valid_from <= now),
                    (GremiumMembership.valid_until.is_(None))
                    | (GremiumMembership.valid_until > now),
                )
            )
        ) or 0
        if members == 0:
            return None
        percent = getattr(gremium, "quorum_percent", None)
        if percent is not None:
            return present_count * 100 >= percent * members
        return present_count * 2 > members

    async def _header_meta(
        self, meeting: Meeting | None
    ) -> tuple[str | None, list[str], list[str]]:
        """Protokollant + Anwesenheits-Listen (Name oder Sub) für den Protokoll-Header."""
        if meeting is None:
            return None, [], []
        protokollant: str | None = None
        if getattr(meeting, "protokollant_id", None) is not None:
            protokollant = await self.session.scalar(
                select(PrincipalRow.display_name).where(
                    PrincipalRow.id == meeting.protokollant_id
                )
            )
        rows = (
            await self.session.execute(
                select(
                    MeetingAttendance.status, PrincipalRow.display_name, PrincipalRow.sub
                )
                .join(PrincipalRow, PrincipalRow.id == MeetingAttendance.principal_id)
                .where(MeetingAttendance.meeting_id == meeting.id)
                .order_by(PrincipalRow.display_name)
            )
        ).all()
        present = [name or sub for status, name, sub in rows if status == "present"]
        absent = [name or sub for status, name, sub in rows if status == "absent"]
        return protokollant, present, absent

    async def _has_non_public(self, meeting_id: UUID) -> bool:
        """Hat die Sitzung mind. einen nicht-öffentlichen TOP? (steuert Dual-Render)."""
        return bool(
            await self.session.scalar(
                select(func.count())
                .select_from(MeetingAgendaItem)
                .where(
                    MeetingAgendaItem.meeting_id == meeting_id,
                    MeetingAgendaItem.non_public.is_(True),
                )
            )
        )

    async def _assemble_from_agenda(
        self, meeting_id: UUID, *, public: bool = False
    ) -> str:
        """Protokoll-Markdown aus den TOP-Bodies + ihren Beschluss-Abstimmungen bauen.

        ``public=True`` redigiert nicht-öffentliche TOPs: die Überschrift (und damit die
        TOP-Nummerierung) bleibt erhalten, Body + Beschluss-Snippets werden durch einen
        Platzhalter ersetzt."""
        items = (
            await self.session.execute(
                select(MeetingAgendaItem)
                .where(MeetingAgendaItem.meeting_id == meeting_id)
                .order_by(MeetingAgendaItem.position)
            )
        ).scalars().all()
        if not items:
            return ""
        voting = VotingService(self.session)
        blocks: list[str] = []
        for item in items:
            heading = (item.title or "Tagesordnungspunkt").strip()
            # Top-Level-``#`` OHNE »TOP n:«-Präfix: pytex nummeriert die Sections
            # selbst als »TOP 1«, »TOP 2«, … (#pdf-format) — ``##`` würde als
            # »TOP 0.1« nummeriert und ein eigenes Präfix doppelt erscheinen.
            block = [f"# {heading}"]
            if public and item.non_public:
                # Überschrift bleibt (Nummerierung stabil), Inhalt redigiert.
                block.append(_NON_PUBLIC_PLACEHOLDER)
                blocks.append("\n\n".join(block))
                continue
            if item.body and item.body.strip():
                # Body-Headings eine Ebene absenken: nur die TOP-Überschrift
                # bleibt Top-Level (sonst zählte jedes ``#`` als eigener TOP).
                block.append(demote_headings(item.body.strip()))
            votes = (
                await self.session.execute(
                    select(Vote)
                    .where(
                        Vote.agenda_item_id == item.id,
                        # Stornierte Abstimmungen (Wahl abgebrochen) haben kein
                        # Ergebnis — keine leere Tally-Box im Protokoll.
                        Vote.status != "cancelled",
                    )
                    .order_by(Vote.created_at)
                )
            ).scalars().all()
            for vote in votes:
                view = await voting.get(vote.id)
                block.append(
                    build_vote_snippet(
                        view.question or "Beschlussfrage",
                        view.tally.counts,
                        question=view.question,
                    )
                )
            blocks.append("\n\n".join(block))
        return "\n\n".join(blocks) + "\n"

    async def _render_pdf(
        self, protocol: Protocol, markdown: str, *, public: bool = False
    ) -> bytes | None:
        """pytex → PDF-Bytes (VOR dem Commit). Setzt die Key-Spalte, lädt aber NICHT
        hoch — der Storage-``put`` läuft post-commit in :meth:`_store`.

        ``public=True`` setzt ``public_pdf_storage_key`` statt ``pdf_storage_key``.
        Ohne Storage »aus« (DEV) wird nicht gerendert (``None``); ein dauerhafter
        pytex-Fehler → 400, ein transienter → 503 (Entwurf bleibt erhalten)."""
        # Storage ist der bewusste An/Aus-Schalter (T-20-Konvention): fehlt er, läuft
        # finalize ohne PDF weiter (Demo/Contract-CI ohne MinIO).
        if self.storage is None or self.pytex is None:
            return None
        try:
            variant = protocol_variant_for(protocol.cd_variant)
            # RCE-Schutz (security.md §2): der nutzer-geschriebene Body (Protokollant)
            # könnte pytex' Markdown-``eval``-Escape (``[//]: # "EXPR"`` → eval im
            # Container) tragen. Den entfernt ``sanitize_user_markdown`` BEDINGUNGSLOS
            # schon beim Zusammenbau (``build_protocol_document``), bevor das Markdown
            # pytex erreicht — der einzige eval-Vektor ist damit weg; ``\write18``-Shell-
            # Escape greift unter der tectonic-Engine ohnehin nicht. Darum rendert
            # dieser Pfad ``trusted`` (Client-Default): die Protokoll-Variante
            # (``protocol-stupa``/``-asta``) braucht pytex' Template-Maschinerie, die
            # ``untrusted`` sperrt — untrusted ließ jeden Protokoll-Render mit 400 (pytex
            # ``TrustError``) scheitern.
            pdf = await self.pytex.render_pdf(markdown, variant=variant)
        except PytexError as exc:
            # 4xx = dauerhafter Eingabe-/Compile-Fehler (z. B. ungültiges LaTeX im
            # Protokoll-Markdown): kein Retry, dem Nutzer den (gescrubbten) Grund
            # zeigen statt eines irreführenden 503. 5xx/Transport bleibt transient.
            if not exc.retryable:
                raise BadRequestError(
                    f"Protocol could not be rendered: {exc}", code="render_failed"
                ) from exc
            raise ServiceUnavailableError(
                "Protocol rendering temporarily unavailable."
            ) from exc
        key = (
            protocol_public_storage_key(protocol.id)
            if public
            else protocol_storage_key(protocol.id)
        )
        if public:
            protocol.public_pdf_storage_key = key
        else:
            protocol.pdf_storage_key = key
        return pdf

    async def _store(self, uploads: list[tuple[str, bytes]]) -> None:
        """Gerenderte PDFs NACH erfolgreichem Commit ins Object-Storage schreiben.

        Erst jetzt entsteht das MinIO-Objekt — schlägt der vorausgehende Commit fehl,
        gibt es kein verwaistes Objekt (#pre-commit-side-effects). Ohne Storage »aus«
        bleibt ``uploads`` leer (``_render_pdf`` lieferte ``None``). Ein transienter
        Storage-Fehler → 503: das Protokoll ist bereits ``final`` committed, der erneute
        ``finalize`` ist über die ``status=='final'``-Idempotenz ein No-Op."""
        if self.storage is None:
            return
        try:
            for key, pdf in uploads:
                await self.storage.put(key, pdf, "application/pdf")
        except StorageError as exc:
            # Vorhandenes Backend transient nicht erreichbar → 503. Kein Pfad-Leak.
            raise ServiceUnavailableError(
                "Protocol rendering temporarily unavailable."
            ) from exc

    async def _send(self, protocol: Protocol, pdf: bytes | None) -> None:
        """Protokoll an MAIL_LIST(gremium) — idempotenter Key, PDF als **Anhang**.

        Subject/Body nennen Gremium + Sitzung (#4); die HTML-Fassung nutzt das
        gebrandete Mail-Layout. Kein Link mehr (#protocol-mail-pdf): der frühere
        ``/api/protocols/{id}/pdf``-Link verlangt Login + ``meeting.manage`` — für
        Mitglieder und externe Verteiler-Adressen war er schlicht kaputt."""
        if self.mail_queue is None:
            return
        recipients = await self._recipients(protocol.gremium_id)
        # Abgewählte Protokoll-Mails respektieren (#4-2).
        recipients = await filter_recipients_by_preference(
            self.session, recipients, "protocol"
        )
        if not recipients:
            return
        gremium_name = await self.session.scalar(
            select(Gremium.name).where(Gremium.id == protocol.gremium_id)
        )
        meeting = await self.session.get(Meeting, protocol.meeting_id)
        subject = "Sitzungsprotokoll"
        if gremium_name:
            subject += f" {gremium_name}"
        if meeting is not None and meeting.date is not None:
            subject += f" — {meeting.date.strftime('%d.%m.%Y')}"
        lines = []
        if meeting is not None:
            lines.append(f"Sitzung: {meeting.title}")
        if gremium_name:
            lines.append(f"Gremium: {gremium_name}")
        if meeting is not None and meeting.date is not None:
            lines.append(f"Datum: {meeting.date.strftime('%d.%m.%Y')}")
        intro = "Das Sitzungsprotokoll wurde finalisiert."
        if pdf is not None:
            intro = (
                "Das Sitzungsprotokoll wurde finalisiert und liegt als PDF bei."
            )
        text = intro + ("\n\n" + "\n".join(lines) if lines else "") + "\n"
        attachments: tuple[MailAttachment, ...] = ()
        if pdf is not None:
            attachments = (
                MailAttachment(
                    filename="protokoll.pdf", mime="application/pdf", content=pdf
                ),
            )
        settings = self.settings or get_settings()
        html = render_layout(
            content_html=text_to_html(text),
            title=subject,
            site_name=settings.mail_from_name,
            base_url=settings.public_base_url,
            reason=reason_text("protocol", "de"),
            lang="de",
        )
        await self.mail_queue.enqueue(
            MailMessage(
                to=tuple(recipients),
                subject=subject,
                text=text,
                html=html,
                idempotency_key=compute_idempotency_key(
                    "protocol_finalized", str(protocol.id)
                ),
                attachments=attachments,
            )
        )

    async def _recipients(self, gremium_id: UUID) -> list[str]:
        """Flache, deduplizierte Empfängerliste des Gremiums.

        **Union** aus den aktiven Gremium-Mitgliedern (Amtszeit-Fenster, email≠NULL)
        und den konfigurierten Zusatz-Verteilern (``mail_list``, pflegbar über
        ``PUT /admin/gremien/{id}/mail-recipients``, #protocol-recipients) — die
        Zusatz-Adressen erhalten das Protokoll **zusätzlich**, nicht statt der
        Mitglieder."""
        seen: dict[str, None] = {}
        members = await RecipientResolver(self.session).resolve(
            [{"kind": "gremium", "ref": str(gremium_id)}]
        )
        for addr in members:
            seen.setdefault(addr, None)
        lists = (
            await self.session.execute(
                select(MailList.recipients).where(
                    MailList.gremium_id == gremium_id, MailList.active.is_(True)
                )
            )
        ).scalars().all()
        for recipients in lists:
            for addr in recipients or []:
                seen.setdefault(addr, None)
        return list(seen)

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _ensure_draft(protocol: Protocol) -> None:
        if protocol.status == "final":
            raise ConflictError(
                "Protocol is finalized and read-only.", code="conflict"
            )
        if protocol.status == "rendering":
            # Während des Hintergrund-Renders ist der Inhalt eingefroren — sonst
            # würde das PDF einen anderen Stand zeigen als der Editor.
            raise ConflictError(
                "Protocol is being rendered and is read-only.", code="conflict"
            )

    async def _get_vote(self, vote_id: UUID) -> Vote:
        vote = await self.session.get(Vote, vote_id)
        if vote is None:
            raise NotFoundError(f"vote {vote_id} not found")
        return vote


def _vote_title(application_id: UUID | None, question: str | None = None) -> str:
    """Snippet-Überschrift einer eingebetteten Abstimmung.

    Antrags-TOP: Kurz-Referenz auf den Antrag. Generische Beschlussfrage (kein
    Antrag): die Frage selbst. Der Protokollant kann die Überschrift im Editor frei
    nacharbeiten."""
    if application_id is not None:
        return f"Abstimmung – Antrag {str(application_id)[:8]}"
    return question.strip() if question and question.strip() else "Beschlussfrage"
