import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  computed,
  effect,
  inject,
  input,
  model,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { type Delegation, DelegationsApiService } from '@core/api/delegations.service';
import type { Attendance, AttendanceStatus, Meeting, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { ButtonComponent, IconComponent, MEDIA, ToastService } from '@stupa-makers/ui-kit';
import { AvatarComponent } from '@shared/ui/avatar/avatar.component';
import {
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
} from '@shared/ui/row-menu/row-menu.component';
import { SideSheetComponent } from '@shared/ui/side-sheet/side-sheet.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import type { StatusKind } from '@shared/status-kind.util';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import { mediaQuerySignal } from '../../../layout/media-query';
import { MeetingDelegationCardComponent } from '../meeting-delegation-card.component';

/** One attendance change. `note` is the reason of an excuse; omitted keeps the stored one. */
export interface AttendanceChange {
  member: Attendance;
  status: AttendanceStatus;
  note?: string | null;
}

/** A choice of the attendance control. `open` resets the record (lead only). */
type Choice = AttendanceStatus | 'open';

/** One option of the control of a row. */
interface ChoiceOption {
  value: Choice;
  label: TranslationKey;
  /** Why the option is not possible now, or `null`. */
  blocked: TranslationKey | null;
}

/** A row of the sheet: the record, its sub line and its control. */
interface Row {
  a: Attendance;
  name: string;
  sub: string;
  /** The options of the control, or `null` for a read-only row. */
  options: ChoiceOption[] | null;
  /** The chosen option. */
  value: Choice;
  /** The read-only status text. */
  readOnly: { kind: StatusKind; key: TranslationKey };
  menu: RowMenuSection[];
  /** O23: the server refused "present" for this member; the delegation is in the way. */
  conflict: Delegation | 'unknown' | null;
}

const LEAD_CHOICES: readonly { value: Choice; label: TranslationKey }[] = [
  { value: 'present', label: 'meetings.attendance.present' },
  { value: 'excused', label: 'meetings.attendance.excused' },
  { value: 'absent', label: 'meetings.attendance.absent' },
  { value: 'open', label: 'meetings.attendance.unknown' },
];

/** A member reports the own record as present or absent (Z2: "Abwesend" means excused). */
const SELF_CHOICES: readonly { value: Choice; label: TranslationKey }[] = [
  { value: 'present', label: 'meetings.attendance.selfPresent' },
  { value: 'excused', label: 'meetings.attendance.selfExcused' },
];

/**
 * The attendance sheet of a meeting (board Sitzung-Anwesenheit).
 *
 * A side sheet from the end edge (a bottom sheet on a phone) with the counts, a member
 * search and one row per member: avatar, name, a sub line (the reason, "durch
 * Sitzungsleitung", "vertreten durch …") and the control.
 *
 * - The meeting lead (`canControl`) sets every row to "Anwesend / Entschuldigt /
 *   Unentschuldigt" and resets it to "Offen" (DELETE). The lead's record wins (O15).
 * - A member reports only the own row, as "Anwesend / Abwesend" (Z2), while the lead
 *   did not set it. Every other row is read-only.
 * - O23: a member with an active delegation cannot be present. The option is disabled
 *   and says why; a 409 from the server marks the row and offers the revoke.
 * - The reason of an excuse shows only to the member and the lead (the server sends it
 *   to them only); the row menu edits it.
 * - A closed meeting freezes the attendance: every row is read-only.
 *
 * Below the members: the delegations of the meeting (the lead revokes one while the
 * meeting is live, O6), the own delegation card and the people who have the meeting open.
 */
@Component({
  selector: 'app-attendance-sheet',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    AvatarComponent,
    RowMenuComponent,
    SideSheetComponent,
    StatusTextComponent,
    ScrollFadeDirective,
    MeetingDelegationCardComponent,
  ],
  templateUrl: './attendance-sheet.component.html',
  styleUrl: './attendance-sheet.component.scss',
})
export class AttendanceSheetComponent {
  private readonly i18n = inject(I18nService);
  private readonly delegationsApi = inject(DelegationsApiService);
  private readonly toast = inject(ToastService);

  /** A phone opens the sheet from the bottom. */
  protected readonly phone = mediaQuerySignal(MEDIA.phone);

  readonly open = model(false);
  readonly meeting = input.required<Meeting>();
  readonly attendance = input.required<Attendance[]>();
  readonly saving = input(false);
  /** Names of the people who have the meeting open (WS presence). */
  readonly viewers = input<string[]>([]);
  /** O23: the member whose "present" the server refused with 409 `delegation_active`. */
  readonly conflictId = input<Uuid | null>(null);

  readonly statusChange = output<AttendanceChange>();
  /** The lead resets a row to "open". */
  readonly reset = output<Attendance>();

  protected readonly query = signal('');
  /** The delegations of the meeting: all of them for the lead, else the own ones. */
  protected readonly delegations = signal<Delegation[]>([]);
  /** The row whose reason is being edited. */
  protected readonly editingNote = signal<Uuid | null>(null);
  protected readonly revoking = signal<Uuid | null>(null);
  /** The reason field of the row in edit; it takes the focus when it appears. */
  private readonly noteInput = viewChild<ElementRef<HTMLInputElement>>('note');

  constructor() {
    // Load the delegations when the sheet opens, and again when the server reports a
    // delegation that this page did not know (409 `delegation_active`).
    effect(() => {
      const open = this.open();
      const id = this.meeting().id;
      this.conflictId();
      if (open) untracked(() => this.loadDelegations(id));
    });
    effect(() => {
      if (!this.open()) {
        untracked(() => {
          this.query.set('');
          this.editingNote.set(null);
        });
      }
    });
    effect(() => this.noteInput()?.nativeElement.focus());
  }

  /** The lead sets every row. A closed meeting freezes the attendance. */
  protected readonly lead = computed(() => this.meeting().canControl);
  protected readonly locked = computed(() => this.meeting().status === 'closed');

  protected readonly counts = computed(() => {
    const rows = this.attendance();
    const count = (s: AttendanceStatus | null) => rows.filter((a) => a.status === s).length;
    return [
      { n: count('present'), key: 'meetings.attendanceSheet.present' as TranslationKey },
      { n: count('excused'), key: 'meetings.attendanceSheet.excused' as TranslationKey },
      { n: count('absent'), key: 'meetings.attendanceSheet.absent' as TranslationKey },
      { n: count(null), key: 'meetings.attendanceSheet.open' as TranslationKey },
    ];
  });

  /** The delegation of a member for this meeting, as the delegator. */
  private delegationOf(principalId: Uuid): Delegation | null {
    return this.delegations().find((d) => d.delegatorId === principalId) ?? null;
  }

  /** The delegations the lead manages: every delegation of the meeting. */
  protected readonly meetingDelegations = computed(() =>
    this.meeting().canManage ? this.delegations() : [],
  );

  protected readonly rows = computed<Row[]>(() => {
    const q = this.query().trim().toLowerCase();
    const t = (key: TranslationKey, params?: Record<string, string | number>) =>
      this.i18n.translate(key, params);
    return this.attendance()
      .filter((a) => !q || [a.displayName, a.email].some((v) => v?.toLowerCase().includes(q)))
      .map((a) => this.row(a, t));
  });

  private row(
    a: Attendance,
    t: (key: TranslationKey, params?: Record<string, string | number>) => string,
  ): Row {
    const delegation = this.delegationOf(a.principalId);
    const sub: string[] = [];
    if (a.note) sub.push(t('meetings.attendanceSheet.reason', { note: a.note }));
    if (delegation) {
      sub.push(t('meetings.attendanceSheet.representedBy', { name: delegation.delegateName ?? '—' }));
      if (delegation.delegateVoting) sub.push(t('meetings.attendanceSheet.withVote'));
    }
    if (a.source === 'lead') sub.push(t('meetings.attendance.bySession'));

    const blocked: TranslationKey | null = delegation ? 'meetings.attendanceSheet.revokeFirst' : null;
    let options: ChoiceOption[] | null = null;
    if (!this.locked()) {
      if (this.lead()) {
        options = LEAD_CHOICES.map((c) => ({ ...c, blocked: c.value === 'present' ? blocked : null }));
      } else if (a.isSelf && a.source !== 'lead') {
        options = SELF_CHOICES.map((c) => ({ ...c, blocked: c.value === 'present' ? blocked : null }));
      }
    }

    const conflict =
      this.conflictId() === a.principalId && a.status !== 'present' ? (delegation ?? 'unknown') : null;
    return {
      a,
      name: a.displayName || a.email || '—',
      sub: sub.join(' · '),
      options,
      value: a.status ?? 'open',
      readOnly: this.readOnly(a.status),
      menu: this.menuOf(a),
      conflict,
    };
  }

  /** The status text of a read-only row. A member reads "Abwesend" for an excuse (Z2). */
  private readOnly(status: AttendanceStatus | null): { kind: StatusKind; key: TranslationKey } {
    if (status === 'present') return { kind: 'accent', key: 'meetings.attendance.present' };
    if (status === null) return { kind: 'muted', key: 'meetings.attendance.unknown' };
    if (!this.lead()) return { kind: 'neutral', key: 'meetings.attendance.selfExcused' };
    return { kind: status === 'absent' ? 'warn' : 'neutral', key: `meetings.attendance.${status}` };
  }

  /**
   * The reason is editable on an excused row: by the member on the own row while the
   * lead did not set it; by the lead on a row the lead set and on the own row. A save
   * from the lead takes the record over (O15), so a member's own reason stays the
   * member's.
   */
  private noteEditable(a: Attendance): boolean {
    if (this.locked() || a.status !== 'excused') return false;
    if (this.lead()) return a.source === 'lead' || a.isSelf;
    return a.isSelf && a.source !== 'lead';
  }

  private menuOf(a: Attendance): RowMenuSection[] {
    const items: RowMenuItem[] = [];
    if (this.noteEditable(a)) {
      items.push({
        id: 'note',
        label: this.i18n.translate(
          a.note ? 'meetings.attendanceSheet.editReason' : 'meetings.attendanceSheet.addReason',
        ),
        icon: 'edit',
      });
    }
    return items.length ? [{ items }] : [];
  }

  protected choose(row: Row, option: ChoiceOption): void {
    if (option.blocked || this.saving() || option.value === row.value) return;
    if (option.value === 'open') {
      this.reset.emit(row.a);
      return;
    }
    this.statusChange.emit({ member: row.a, status: option.value });
  }

  /** Arrow keys move the choice, as in a radio group. A blocked option is skipped. */
  protected onKey(event: KeyboardEvent, row: Row, index: number): void {
    const options = row.options;
    if (!options) return;
    const dir = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1
      : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0;
    if (!dir) return;
    event.preventDefault();
    for (let i = 1; i <= options.length; i++) {
      const next = (index + dir * i + options.length) % options.length;
      if (options[next].blocked) continue;
      const group = (event.currentTarget as HTMLElement).parentElement;
      group?.querySelectorAll<HTMLButtonElement>('[role="radio"]')[next]?.focus();
      this.choose(row, options[next]);
      return;
    }
  }

  protected onMenu(row: Row, item: RowMenuItem): void {
    if (item.id === 'note') this.editingNote.set(row.a.principalId);
  }

  /** Save a changed reason. An empty field removes it. */
  protected saveNote(a: Attendance, value: string): void {
    if (this.editingNote() !== a.principalId) return;
    this.editingNote.set(null);
    const note = value.trim() || null;
    if (note === a.note) return;
    this.statusChange.emit({ member: a, status: 'excused', note });
  }

  protected cancelNote(event: Event): void {
    event.stopPropagation();
    this.editingNote.set(null);
  }

  /** Revoke a delegation of the meeting (the lead while live, O6, or the delegator). */
  protected revoke(d: Delegation): void {
    if (this.revoking()) return;
    this.revoking.set(d.id);
    this.delegationsApi.revoke(d.id).subscribe({
      next: () => {
        this.revoking.set(null);
        this.toast.success(this.i18n.translate('delegation.toast.revoked'));
        this.loadDelegations(this.meeting().id);
      },
      error: () => {
        this.revoking.set(null);
        this.toast.error(this.i18n.translate('delegation.toast.revokeFailed'));
      },
    });
  }

  protected delegationLine(d: Delegation): string {
    return `${d.delegatorName ?? '—'} → ${d.delegateName ?? '—'}`;
  }

  private loadDelegations(meetingId: Uuid): void {
    this.delegationsApi.list(meetingId).subscribe({
      next: (rows) => {
        if (this.meeting().id === meetingId) this.delegations.set(rows.filter((d) => d.meetingId === meetingId));
      },
      error: () => this.delegations.set([]),
    });
  }
}
