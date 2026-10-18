import { Injectable, type OnDestroy, computed, inject, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { AsyncSubject, type Observable, map, of, switchMap } from 'rxjs';
import type { AgendaItem, Uuid } from '@core/api/models';
import { errorDetail } from './meetings-display.util';

/** Idle time after the last keystroke before the service autosaves the TOP body. */
const AUTOSAVE_DELAY_MS = 1000;

/**
 * Agenda (TOP) state of the loaded meeting: item CRUD, inline rename, reorder by drag
 * and drop or by the row menu, per-TOP selection and the debounced body autosave.
 * MeetingsComponent provides this service.
 */
@Injectable()
export class MeetingAgendaService implements OnDestroy {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly agenda = signal<AgendaItem[]>([]);
  readonly savingAgenda = signal(false);
  /** Inline rename of a freetext TOP: the active item and the draft input. */
  readonly renamingTopId = signal<Uuid | null>(null);
  readonly renameDraft = signal<string>('');

  /** TOP currently selected in the editor pane. */
  readonly selectedTopId = signal<Uuid | null>(null);
  readonly savingTop = signal(false);
  /** Autosave state of the current TOP body. */
  readonly saveState = signal<'idle' | 'saving' | 'saved' | 'error'>('idle');
  private bodyTimer: ReturnType<typeof setTimeout> | null = null;
  /**
   * The item a link asks for (`?item=` of `/meetings/:id`, from a to-do link). The first
   * read of the agenda that holds it selects it, ahead of the item the room handles now.
   */
  private requestedTopId: Uuid | null = null;
  /** Debounced TOP edit that the server does not hold yet: the item and the text. */
  private pendingBody: { meetingId: Uuid; itemId: Uuid; body: string } | null = null;
  /**
   * The newest text of an item that this tab has typed and the server has not confirmed
   * yet. A read of the agenda keeps it in place of the text of the server, because a read
   * that started before the save (for example the agenda reload after the
   * `meeting_state` of an earlier save) would set the item back to an older text. The
   * next insert, like a vote result, appends to the text of the item, so that older text
   * would replace what the minute-taker typed last.
   */
  private localBody: { itemId: Uuid; body: string } | null = null;
  /** The running body save. It emits once and completes after the response. */
  private runningSave: Observable<void> | null = null;

  readonly selectedTop = computed<AgendaItem | null>(
    () => this.agenda().find((a) => a.id === this.selectedTopId()) ?? null,
  );
  readonly selectedIndex = computed(() =>
    this.agenda().findIndex((a) => a.id === this.selectedTopId()),
  );

  /**
   * Show a refused agenda change with the server reason. A closed meeting answers
   * 409 `meeting_closed`, and an item with an open or closed vote answers 409
   * `agenda_item_has_vote`.
   */
  private failed(err: unknown): void {
    const detail = errorDetail(err);
    const base = this.i18n.translate('meetings.toast.actionFailed');
    this.toast.error(detail ? `${base}: ${detail}` : base);
  }

  /** Save a pending edit when the page goes away, so that the debounce drops no text. */
  ngOnDestroy(): void {
    this.flushPendingBody(this.pendingBody?.meetingId ?? null);
  }

  /**
   * Load the agenda. Later calls are quiet refreshes after a WS event or a failed drop.
   *
   * An item that a link asks for (`requestTop`) is opened once it is on the agenda.
   * Without it and without a valid selection the item the room handles now
   * (`preferred`) is opened, else the first item.
   */
  load(meetingId: Uuid, preferred: Uuid | null = null): void {
    this.api.listAgenda(meetingId, { quiet: true }).subscribe({
      next: (rows) => {
        this.setRows(rows);
        const sel = this.selectedTopId();
        const wanted = this.requestedTopId;
        if (wanted && rows.some((r) => r.id === wanted)) {
          this.requestedTopId = null;
          this.selectedTopId.set(wanted);
        } else if (!sel || !rows.some((r) => r.id === sel)) {
          const now = preferred && rows.some((r) => r.id === preferred) ? preferred : null;
          this.selectedTopId.set(now ?? rows[0]?.id ?? null);
        }
      },
      error: () => this.agenda.set([]),
    });
  }

  removeFromAgenda(meetingId: Uuid, itemId: Uuid): void {
    if (this.savingAgenda()) return;
    this.savingAgenda.set(true);
    this.api.removeAgendaItem(meetingId, itemId).subscribe({
      next: (rows) => {
        this.savingAgenda.set(false);
        this.setRows(rows);
        this.toast.success(this.i18n.translate('meetings.toast.agendaItemRemoved'));
      },
      error: (err: unknown) => {
        this.savingAgenda.set(false);
        this.failed(err);
      },
    });
  }

  /** Start inline rename of a freetext TOP (application TOPs keep their title). */
  startRename(item: AgendaItem): void {
    if (item.applicationId) return;
    this.renamingTopId.set(item.id);
    this.renameDraft.set(item.title ?? '');
  }

  cancelRename(): void {
    this.renamingTopId.set(null);
    this.renameDraft.set('');
  }

  renameTop(meetingId: Uuid | null, item: AgendaItem): void {
    // Ignore a stale call after a cancel or a switch. This blocks a second save on blur.
    if (this.renamingTopId() !== item.id) return;
    const title = this.renameDraft().trim();
    if (!meetingId || item.applicationId || !title || title === (item.title ?? '')) {
      this.cancelRename();
      return;
    }
    this.renamingTopId.set(null);
    this.savingAgenda.set(true);
    this.api.renameAgendaItem(meetingId, item.id, title).subscribe({
      next: (rows) => {
        this.savingAgenda.set(false);
        this.setRows(rows);
        this.renameDraft.set('');
      },
      error: (err: unknown) => {
        this.savingAgenda.set(false);
        this.failed(err);
      },
    });
  }

  /** Mark a TOP as public or non-public. The public PDF redacts a non-public TOP. */
  setNonPublic(meetingId: Uuid, item: AgendaItem, nonPublic: boolean): void {
    this.savingAgenda.set(true);
    this.api.setAgendaNonPublic(meetingId, item.id, nonPublic).subscribe({
      next: (rows) => {
        this.savingAgenda.set(false);
        this.setRows(rows);
      },
      error: (err: unknown) => {
        this.savingAgenda.set(false);
        this.failed(err);
      },
    });
  }

  /**
   * Move the item at `from` to `to` (0-based) and save the new order. The list changes
   * at once; a refused save reloads the agenda.
   */
  moveTop(meetingId: Uuid | null, from: number, to: number): void {
    const items = [...this.agenda()];
    if (!meetingId || from === to || !items[from] || to < 0 || to >= items.length) return;
    const [moved] = items.splice(from, 1);
    items.splice(to, 0, moved);
    this.agenda.set(items); // optimistic update
    this.api.reorderAgenda(meetingId, items.map((i) => i.id)).subscribe({
      next: (rows) => this.setRows(rows),
      error: (err: unknown) => {
        this.failed(err);
        this.load(meetingId);
      },
    });
  }

  /**
   * Open the item that a link names (`?item=`). The item is selected at once when the
   * agenda holds it, else at the next read of the agenda. The room does not move.
   */
  requestTop(id: Uuid | null): void {
    this.requestedTopId = id;
    if (id && this.agenda().some((a) => a.id === id)) {
      this.requestedTopId = null;
      this.selectedTopId.set(id);
    }
  }

  /**
   * Select a TOP.
   *
   * The method first flushes a pending autosave of the previous TOP body. Without
   * that flush, the next debounce cancel drops the edit without a message.
   */
  selectTop(meetingId: Uuid | null, id: Uuid): void {
    this.flushPendingBody(meetingId);
    this.selectedTopId.set(id);
  }

  /** Debounce the save of the TOP body. The local text changes at once. */
  onTopBodyChange(meetingId: Uuid, itemId: Uuid, body: string): void {
    if (this.bodyTimer !== null) clearTimeout(this.bodyTimer);
    this.pendingBody = { meetingId, itemId, body };
    this.localBody = { itemId, body };
    this.agenda.update((items) =>
      items.map((a) => (a.id === itemId ? { ...a, body } : a)),
    );
    this.saveState.set('idle');
    this.bodyTimer = setTimeout(() => {
      this.saveBody(meetingId, itemId, body);
    }, AUTOSAVE_DELAY_MS);
  }

  /** Run a pending autosave at once on a TOP switch so that no edit is lost. */
  flushPendingBody(meetingId: Uuid | null): void {
    if (this.bodyTimer === null || this.pendingBody === null) return;
    clearTimeout(this.bodyTimer);
    const { itemId, body } = this.pendingBody;
    if (!meetingId) {
      this.bodyTimer = null;
      this.pendingBody = null;
      this.localBody = null;
      return;
    }
    this.saveBody(meetingId, itemId, body);
  }

  /**
   * Run a pending autosave at once and wait for the body save.
   *
   * The observable emits once and completes when no body save runs anymore, also
   * after a failed save. A caller that changes the write right (the handover)
   * waits for it, so that the save does not race the change.
   */
  settlePendingBody(meetingId: Uuid | null): Observable<void> {
    this.flushPendingBody(meetingId);
    return this.runningSave ?? of(undefined);
  }

  /**
   * Make sure that the server holds the text that this tab shows, and tell if it does.
   *
   * The finalize renders the protocol from the item texts on the server, and a body
   * save after the finalize gets 409 `protocol_locked`. So the finalize waits for this:
   * it runs a pending autosave at once and waits for a running save. Without either,
   * it sends the text of an earlier failed save again. The observable emits `false` when the server still
   * does not hold the text.
   */
  persistBody(meetingId: Uuid): Observable<boolean> {
    // A save that runs now is the try. Only an earlier failed save is sent again.
    const busy = this.bodyTimer !== null || this.runningSave !== null;
    return this.settlePendingBody(meetingId).pipe(
      switchMap(() => {
        const local = this.localBody;
        if (busy || !local) return of(undefined);
        this.saveBody(meetingId, local.itemId, local.body);
        return this.runningSave ?? of(undefined);
      }),
      map(() => this.localBody === null),
    );
  }

  private saveBody(meetingId: Uuid, itemId: Uuid, body: string): void {
    this.bodyTimer = null;
    this.pendingBody = null;
    this.savingTop.set(true);
    this.saveState.set('saving');
    const done = new AsyncSubject<void>();
    const running = done.asObservable();
    this.runningSave = running;
    const settle = (): void => {
      if (this.runningSave === running) this.runningSave = null;
      done.next();
      done.complete();
    };
    this.api.setAgendaBody(meetingId, itemId, body).subscribe({
      next: (rows) => {
        this.savingTop.set(false);
        // The server holds the newest text now, unless the minute-taker typed again.
        const local = this.localBody;
        if (local?.itemId === itemId && local.body === body) this.localBody = null;
        this.setRows(rows);
        this.saveState.set('saved');
        settle();
      },
      error: () => {
        this.savingTop.set(false);
        this.saveState.set('error');
        settle();
      },
    });
  }

  /** Show the rows of the server, with the unconfirmed text of this tab kept. */
  private setRows(rows: AgendaItem[]): void {
    const local = this.localBody;
    this.agenda.set(
      local
        ? rows.map((a) => (a.id === local.itemId ? { ...a, body: local.body } : a))
        : rows,
    );
  }
}
