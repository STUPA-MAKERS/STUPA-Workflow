"""Protokoll-Service (T-22, api.md »protocol«, flows §7).

An eine ``AsyncSession`` gebundener Service für den Protokoll-Lebenszyklus:

* :meth:`get_or_create` — Protokoll einer Sitzung anlegen **oder** laden (idempotent
  über UNIQUE ``meeting_id``); übernimmt ``gremium_id``/``cd_variant`` von Sitzung+Gremium.
* :meth:`update_markdown` — Editor-Body aktualisieren (nur im Entwurf).
* :meth:`embed_votes` — Abstimmungen als Markdown-Snippets anhängen + ``protocol_vote_ref``
  schreiben (idempotent: schon referenzierte Votes werden übersprungen).
* :meth:`finalize` — Markdown → pytex → PDF → MinIO → (Nextcloud) → Mail an
  MAIL_LIST(gremium); ``status='final'`` + ``sent_at``.

**Wiederverwendung T-20** (keine Duplikation): pytex-Client, Object-Storage,
Nextcloud-Exporter und die Mail-Queue/-``MailMessage`` stammen unverändert aus
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
from app.modules.files.storage import ObjectStorage, StorageError
from app.modules.livevote.models import Meeting
from app.modules.notifications.mail import MailMessage, compute_idempotency_key
from app.modules.notifications.queue import MailQueue
from app.modules.pdf.nextcloud import NextcloudError, NextcloudExporter
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
        nextcloud: NextcloudExporter | None = None,
        mail_queue: MailQueue | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.storage = storage
        self.pytex = pytex
        self.nextcloud = nextcloud
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

    def _pdf_url(self, protocol: Protocol) -> str | None:
        """Kurzlebige, signierte Ergebnis-URL (nie ein direkter Bucket-Link)."""
        if (
            protocol.pdf_storage_key is not None
            and self.storage is not None
            and self.settings is not None
        ):
            return self.storage.presigned_get_url(
                protocol.pdf_storage_key,
                expires_seconds=self.settings.pdf_url_ttl_seconds,
                download_name=f"protokoll-{protocol.meeting_id}.pdf",
            )
        return None

    def _to_out(self, protocol: Protocol) -> ProtocolOut:
        return ProtocolOut(
            id=protocol.id,
            meetingId=protocol.meeting_id,
            markdown=protocol.markdown,
            status=protocol.status,  # type: ignore[arg-type]
            pdfUrl=self._pdf_url(protocol),
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
                    _vote_title(view.application_id),
                    view.tally.result,
                    view.tally.counts,
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
    async def finalize(self, protocol_id: UUID, *, now: datetime) -> ProtocolOut:
        """Markdown → PDF → MinIO/Nextcloud → Mail an MAIL_LIST(gremium); ``final``.

        Idempotent: ein bereits finalisiertes Protokoll wird unverändert (mit frisch
        signierter URL) zurückgegeben — kein zweiter Render, kein Doppelversand."""
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
        return build_protocol_document(
            ProtocolDoc(
                title=title,
                gremium_slug=gremium.slug if gremium is not None else None,
                cd_variant=protocol.cd_variant,
                date=meeting.date if meeting is not None else None,
                markdown=protocol.markdown,
            )
        )

    async def _render(self, protocol: Protocol, markdown: str) -> None:
        """pytex → PDF → MinIO → (Nextcloud). Ohne Storage »aus« (DEV); Backend-Fehler → 503."""
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
            if self.nextcloud is not None:
                protocol.nextcloud_path = await self.nextcloud.put_pdf(
                    f"protokoll-{protocol.id}.pdf", pdf
                )
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
        except (StorageError, NextcloudError) as exc:
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
        pdf_url = self._pdf_url(protocol)
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
        """Flache, deduplizierte Empfängerliste aus den aktiven Verteilern des Gremiums."""
        lists = (
            await self.session.execute(
                select(MailList.recipients).where(
                    MailList.gremium_id == gremium_id, MailList.active.is_(True)
                )
            )
        ).scalars().all()
        seen: dict[str, None] = {}
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

    async def _get_vote(self, vote_id: UUID) -> Vote:
        vote = await self.session.get(Vote, vote_id)
        if vote is None:
            raise NotFoundError(f"vote {vote_id} not found")
        return vote


def _vote_title(application_id: UUID) -> str:
    """Snippet-Überschrift einer eingebetteten Abstimmung (Antrags-Referenz).

    ``VoteConfig`` trägt keinen Titel (strikt validiert) — der Bezug ist der Antrag.
    Die Kurz-Referenz unterscheidet mehrere eingebettete Votes; der Protokollant
    kann die Überschrift im Editor frei nacharbeiten."""
    return f"Abstimmung – Antrag {str(application_id)[:8]}"
