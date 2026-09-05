import { Injectable, type OnDestroy, computed, inject, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService } from '@stupa-makers/ui-kit';
import type { SelectOption } from '@stupa-makers/ui-kit';
import type { AgendaItem, AssignableApplication, Uuid } from '@core/api/models';
import { resolveI18n } from './meetings-display.util';

/** Idle time after the last keystroke before the service autosaves the TOP body. */
const AUTOSAVE_DELAY_MS = 1000;

/**
 * Agenda (TOP) state of the loaded meeting: item CRUD, inline rename, drag and drop
 * reorder, per-TOP selection and the debounced body autosave.
 * MeetingsComponent provides this service.
 */
@Injectable()
export class MeetingAgendaService implements OnDestroy {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly agenda = signal<AgendaItem[]>([]);
  readonly assignable = signal<AssignableApplication[]>([]);
  readonly savingAgenda = signal(false);
  readonly agendaPick = signal<string>('');
  readonly agendaFreetext = signal<string>('');
  /** Inline rename of a freetext TOP: the active item and the draft input. */
  readonly renamingTopId = signal<Uuid | null>(null);
  readonly renameDraft = signal<string>('');

  /** TOP currently selected in the editor pane. */
  readonly selectedTopId = signal<Uuid | null>(null);
  readonly savingTop = signal(false);
  /** Autosave state of the current TOP body. */
  readonly saveState = signal<'idle' | 'saving' | 'saved' | 'error'>('idle');
  private bodyTimer: ReturnType<typeof setTimeout> | null = null;
  /** Debounced TOP edit that the server does not hold yet: the item and the text. */
  private pendingBody: { itemId: Uuid; body: string } | null = null;
  private dragTopIndex: number | null = null;

  readonly selectedTop = computed<AgendaItem | null>(
    () => this.agenda().find((a) => a.id === this.selectedTopId()) ?? null,
  );
  readonly selectedIndex = computed(() =>
    this.agenda().findIndex((a) => a.id === this.selectedTopId()),
  );

  readonly assignableOptions = computed<SelectOption[]>(() =>
    this.assignable().map((a) => {
      const title = a.title || a.applicationId;
      const state = resolveI18n(a.stateLabel, this.i18n.locale());
      return { value: a.applicationId, label: state ? `${title} (${state})` : title };
    }),
  );

  ngOnDestroy(): void {
    if (this.bodyTimer !== null) clearTimeout(this.bodyTimer);
  }

  /**
   * Load the agenda. Later calls are quiet refreshes after a WS event or a failed drop.
   *
   * Without a valid selection the item the room handles now (`preferred`) is opened,
   * else the first item.
   */
  load(meetingId: Uuid, canManage: boolean, preferred: Uuid | null = null): void {
    this.api.listAgenda(meetingId, { quiet: true }).subscribe({
      next: (rows) => {
        this.agenda.set(rows);
        const sel = this.selectedTopId();
        if (!sel || !rows.some((r) => r.id === sel)) {
          const now = preferred && rows.some((r) => r.id === preferred) ? preferred : null;
          this.selectedTopId.set(now ?? rows[0]?.id ?? null);
        }
      },
      error: () => this.agenda.set([]),
    });
    if (canManage) this.refreshAssignable(meetingId);
  }

  refreshAssignable(meetingId: Uuid): void {
    this.api.listAssignableApplications(meetingId).subscribe({
      next: (rows) => this.assignable.set(rows),
      error: () => this.assignable.set([]),
    });
  }

  addToAgenda(meetingId: Uuid): void {
    const appId = this.agendaPick();
    if (!appId || this.savingAgenda()) return;
    this.savingAgenda.set(true);
    this.api.addAgendaItem(meetingId, appId).subscribe({
      next: (rows) => {
        this.savingAgenda.set(false);
        this.agenda.set(rows);
        this.agendaPick.set('');
        this.refreshAssignable(meetingId);
      },
      error: () => {
        this.savingAgenda.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  addFreetext(meetingId: Uuid): void {
    const title = this.agendaFreetext().trim();
    if (!title || this.savingAgenda()) return;
    this.savingAgenda.set(true);
    this.api.addAgendaFreetext(meetingId, title).subscribe({
      next: (rows) => {
        this.savingAgenda.set(false);
        this.agenda.set(rows);
        this.agendaFreetext.set('');
      },
      error: () => {
        this.savingAgenda.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  removeFromAgenda(meetingId: Uuid, itemId: Uuid): void {
    if (this.savingAgenda()) return;
    this.savingAgenda.set(true);
    this.api.removeAgendaItem(meetingId, itemId).subscribe({
      next: (rows) => {
        this.savingAgenda.set(false);
        this.agenda.set(rows);
        this.refreshAssignable(meetingId);
      },
      error: () => {
        this.savingAgenda.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
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
        this.agenda.set(rows);
        this.renameDraft.set('');
      },
      error: () => {
        this.savingAgenda.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  /** Mark a TOP as public or non-public. The public PDF redacts a non-public TOP. */
  setNonPublic(meetingId: Uuid, item: AgendaItem, nonPublic: boolean): void {
    this.savingAgenda.set(true);
    this.api.setAgendaNonPublic(meetingId, item.id, nonPublic).subscribe({
      next: (rows) => {
        this.savingAgenda.set(false);
        this.agenda.set(rows);
      },
      error: () => {
        this.savingAgenda.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }

  onTopDragStart(index: number): void {
    this.dragTopIndex = index;
  }

  onTopDragOver(event: DragEvent): void {
    if (this.dragTopIndex !== null) event.preventDefault();
  }

  onTopDrop(meetingId: Uuid | null, index: number, canManage: boolean): void {
    const from = this.dragTopIndex;
    this.dragTopIndex = null;
    if (from === null || from === index || !meetingId) return;
    const items = [...this.agenda()];
    const [moved] = items.splice(from, 1);
    items.splice(index, 0, moved);
    this.agenda.set(items); // optimistic update
    this.api.reorderAgenda(meetingId, items.map((i) => i.id)).subscribe({
      next: (rows) => this.agenda.set(rows),
      error: () => {
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
        this.load(meetingId, canManage);
      },
    });
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
    this.pendingBody = { itemId, body };
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
      return;
    }
    this.saveBody(meetingId, itemId, body);
  }

  private saveBody(meetingId: Uuid, itemId: Uuid, body: string): void {
    this.bodyTimer = null;
    this.pendingBody = null;
    this.savingTop.set(true);
    this.saveState.set('saving');
    this.api.setAgendaBody(meetingId, itemId, body).subscribe({
      next: (rows) => {
        this.savingTop.set(false);
        this.agenda.set(rows);
        this.saveState.set('saved');
      },
      error: () => {
        this.savingTop.set(false);
        this.saveState.set('error');
      },
    });
  }
}
