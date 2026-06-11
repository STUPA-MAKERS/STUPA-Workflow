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

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Gremium, MailList
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.files.storage import ObjectStorage, StorageError
from app.modules.livevote.models import Meeting, MeetingAgendaItem, MeetingAttendance
from app.modules.notifications.mail import MailMessage, compute_idempotency_key
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.recipients import RecipientResolver
from app.modules.pdf.pytex_client import PytexClient, PytexError
from app.modules.protocol.markdown import (
    ProtocolDoc,
    build_protocol_document,
    build_vote_snippet,
    protocol_variant_for,
)
from app.modules.protocol.models import Protocol, ProtocolVoteRef
from app.modules.protocol.schemas import ProtocolOut
from app.modules.voting.models import Vote
from app.modules.voting.service import VotingService
from app.settings import Settings
from app.shared.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
)


def protocol_storage_key(protocol_id: UUID) -> str:
    """Deterministischer MinIO-Key (eigener ``pdf/protocol/``-Präfix, T-20-Schema)."""
    return f"pdf/protocol/{protocol_id}.pdf"


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

    def _to_out(self, protocol: Protocol) -> ProtocolOut:
        return ProtocolOut(
            id=protocol.id,
            meetingId=protocol.meeting_id,
            markdown=protocol.markdown,
            status=protocol.status,  # type: ignore[arg-type]
            pdfUrl=self._pdf_path(protocol),
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
                    view.tally.result,
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

        markdown = await self._build_document(protocol)
        await self._render(protocol, markdown)
        protocol.status = "final"
        protocol.sent_at = now
        await self.session.flush()
        await self._send(protocol)
        await self.session.commit()
        return self._to_out(protocol)

    # ----------------------------------------------------------- finalize bits
    async def _build_document(self, protocol: Protocol) -> str:
        meeting = await self.session.get(Meeting, protocol.meeting_id)
        gremium = await self.session.get(Gremium, protocol.gremium_id)
        title = meeting.title if meeting is not None else "Protokoll"
        # Quelle der Wahrheit ist der pro-TOP-Editor (Tagesordnung). Existieren TOPs,
        # wird das Protokoll aus ihren Markdown-Bodies + Beschluss-Snippets montiert;
        # andernfalls Fallback auf das frei editierte ``protocol.markdown`` (Bestand).
        assembled = await self._assemble_from_agenda(protocol.meeting_id)
        protokollant, present, absent = await self._header_meta(meeting)
        return build_protocol_document(
            ProtocolDoc(
                title=title,
                gremium_name=getattr(gremium, "name", None) if gremium is not None else None,
                cd_variant=protocol.cd_variant,
                date=meeting.date if meeting is not None else None,
                start_time=getattr(meeting, "start_time", None) if meeting is not None else None,
                protokollant=protokollant,
                present=present,
                absent=absent,
                markdown=assembled or protocol.markdown,
            )
        )

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

    async def _assemble_from_agenda(self, meeting_id: UUID) -> str:
        """Protokoll-Markdown aus den TOP-Bodies + ihren Beschluss-Abstimmungen bauen."""
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
        for idx, item in enumerate(items, start=1):
            heading = (item.title or "Tagesordnungspunkt").strip()
            block = [f"## TOP {idx}: {heading}"]
            if item.body and item.body.strip():
                block.append(item.body.strip())
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
                        view.tally.result,
                        view.tally.counts,
                        question=view.question,
                    )
                )
            blocks.append("\n\n".join(block))
        return "\n\n".join(blocks) + "\n"

    async def _render(self, protocol: Protocol, markdown: str) -> None:
        """pytex → PDF → MinIO. Ohne Storage »aus« (DEV); Backend-Fehler → 503."""
        # Storage ist der bewusste An/Aus-Schalter (T-20-Konvention): fehlt er, läuft
        # finalize ohne PDF weiter (Demo/Contract-CI ohne MinIO).
        if self.storage is None or self.pytex is None:
            return
        try:
            variant = protocol_variant_for(protocol.cd_variant)
            pdf = await self.pytex.render_pdf(markdown, variant=variant)
            key = protocol_storage_key(protocol.id)
            await self.storage.put(key, pdf, "application/pdf")
            protocol.pdf_storage_key = key
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
        except StorageError as exc:
            # Vorhandenes Backend transient nicht erreichbar → 503, Entwurf bleibt
            # erhalten (Session-Rollback), Aufruf wiederholbar. Kein Pfad-Leak.
            raise ServiceUnavailableError(
                "Protocol rendering temporarily unavailable."
            ) from exc

    async def _send(self, protocol: Protocol) -> None:
        """Protokoll-PDF an MAIL_LIST(gremium) — idempotenter Key, PDF-Link im Body."""
        if self.mail_queue is None:
            return
        recipients = await self._recipients(protocol.gremium_id)
        if not recipients:
            return
        pdf_path = self._pdf_path(protocol)
        base = self.settings.public_base_url.rstrip("/") if self.settings else ""
        pdf_url = f"{base}{pdf_path}" if pdf_path else None
        link = f"\n\nPDF: {pdf_url}" if pdf_url else ""
        await self.mail_queue.enqueue(
            MailMessage(
                to=tuple(recipients),
                subject="Sitzungsprotokoll",
                text=f"Das Sitzungsprotokoll wurde finalisiert.{link}",
                idempotency_key=compute_idempotency_key(
                    "protocol_finalized", str(protocol.id)
                ),
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
