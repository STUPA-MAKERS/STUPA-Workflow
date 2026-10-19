import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  afterRenderEffect,
  computed,
  inject,
  input,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { forkJoin, type Subscription } from 'rxjs';
import {
  GremienApiService,
  type GremiumAttendanceState,
  type GremiumMemberMeeting,
} from '@core/api/gremien.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { StatusView } from '@shared/status-kind.util';
import {
  AvatarComponent,
  EmptyStateComponent,
  MEDIA,
  mediaQuery,
  NoteComponent,
  placeBelow,
  showInTopLayer,
  SideSheetComponent,
  SkeletonComponent,
  StatusTextComponent,
  watchAnchoredPopover,
} from '@stupa-makers/ui-kit';
import { dayMonth, monthLabel } from '../gremien.util';

/** The gap between the cell and the popover, and the least gap to the viewport edge. */
const GAP = 6;
const EDGE = 8;

let nextId = 0;

/** What the popover or the sheet shows: one person, one month or several months. */
export interface AttendanceDetailRequest {
  readonly principalId: string;
  readonly name: string;
  /** The heading: "Finn Schulze · September" or the name. */
  readonly heading: string;
  /** The line under the heading: "1 von 2 Sitzungen anwesend, 1 entschuldigt". */
  readonly summary: string;
  /** The months (`YYYY-MM`) to read, the newest first. */
  readonly months: readonly string[];
}

export interface AttendanceDetailGroup {
  readonly month: string;
  readonly label: string;
  readonly meetings: readonly GremiumMemberMeeting[];
}

export const ATTENDANCE_STATE: Record<GremiumAttendanceState, StatusView> = {
  present: { kind: 'accent', key: 'gremien.attendance.state.present' },
  excused: { kind: 'warn', key: 'gremien.attendance.state.excused' },
  absent: { kind: 'error', key: 'gremien.attendance.state.absent' },
  delegated: { kind: 'neutral', key: 'gremien.attendance.state.delegated' },
};

/**
 * The meetings of one person with the state in each: a popover on a cell of the matrix
 * (one month), or on a phone the bottom sheet of the person (every month of the range
 * with a meeting).
 *
 * The component has no trigger of its own. The matrix calls `open(request, anchor)`.
 * The popover sits under the cell, inside the viewport; Escape and a pointer down outside
 * close it, and the focus goes back to the cell. It reads
 * `GET /gremien/{id}/attendance/{principalId}?month=` once per month. The excuse text is
 * never in the answer, so it never shows.
 */
@Component({
  selector: 'app-attendance-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NoteComponent,
    EmptyStateComponent,
    NgTemplateOutlet,
    TranslatePipe,
    AvatarComponent,
    SideSheetComponent,
    SkeletonComponent,
    StatusTextComponent,
  ],
  templateUrl: './attendance-detail.component.html',
  styleUrl: './attendance-detail.component.scss',
})
export class AttendanceDetailComponent {
  private readonly api = inject(GremienApiService);
  private readonly i18n = inject(I18nService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  readonly gremiumId = input.required<string>();
  /** A phone viewport: the bottom sheet instead of the popover. */
  readonly phone = mediaQuery(MEDIA.phone);
  readonly headingId = `gad-title-${nextId++}`;

  readonly request = signal<AttendanceDetailRequest | null>(null);
  readonly isOpen = computed(() => this.request() !== null);
  readonly loading = signal(false);
  readonly error = signal(false);
  readonly groups = signal<readonly AttendanceDetailGroup[]>([]);
  readonly empty = computed(() => this.groups().every((g) => g.meetings.length === 0));

  private anchor: HTMLElement | null = null;
  private sub: Subscription | null = null;
  private shownEl: HTMLElement | null = null;
  private readonly pop = viewChild<ElementRef<HTMLElement>>('pop');
  private readonly layer = viewChild<ElementRef<HTMLElement>>('layer');

  constructor() {
    watchAnchoredPopover({
      isOpen: () => this.isOpen() && !this.phone(),
      inside: () => [this.pop()?.nativeElement, this.anchor],
      close: () => this.close(false),
      follow: () => this.place(),
    });
    inject(DestroyRef).onDestroy(() => this.sub?.unsubscribe());

    afterRenderEffect(() => {
      const open = this.isOpen();
      const phone = this.phone();
      const el = (phone ? this.layer() : this.pop())?.nativeElement ?? null;
      untracked(() => this.reveal(open, phone, el));
    });
  }

  /** Open for `request`, under `anchor` (on a phone: the bottom sheet). */
  open(request: AttendanceDetailRequest, anchor: EventTarget | null = null): void {
    this.anchor = anchor instanceof HTMLElement ? anchor : null;
    this.request.set(request);
    this.load(request);
  }

  /** Close; `returnFocus` puts the focus back on the cell. */
  close(returnFocus = true): void {
    if (!this.isOpen()) return;
    this.sub?.unsubscribe();
    this.request.set(null);
    if (returnFocus) this.anchor?.focus();
  }

  onKey(event: KeyboardEvent): void {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    this.close(true);
  }

  /** The sheet closed itself (Escape, scrim, close button, swipe). */
  onSheetOpen(open: boolean): void {
    if (!open) this.close(false);
  }

  /** Read the months again after a failed read. */
  retry(): void {
    const request = this.request();
    if (request) this.load(request);
  }

  state(status: GremiumAttendanceState): StatusView {
    return ATTENDANCE_STATE[status];
  }

  day(value: string | null): string {
    return dayMonth(value, this.i18n.locale());
  }

  private load(request: AttendanceDetailRequest): void {
    this.sub?.unsubscribe();
    this.loading.set(true);
    this.error.set(false);
    this.groups.set([]);
    const months = request.months;
    if (!months.length) {
      this.loading.set(false);
      return;
    }
    const multi = months.length > 1;
    this.sub = forkJoin(
      months.map((m) => this.api.memberAttendance(this.gremiumId(), request.principalId, m)),
    ).subscribe({
      next: (answers) => {
        this.groups.set(
          answers.map((a) => ({
            month: a.month,
            label: multi ? monthLabel(a.month, this.i18n.locale(), 'long') : '',
            meetings: a.meetings,
          })),
        );
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  /** Put the element into the top layer once, place the popover and give it the focus. */
  private reveal(open: boolean, phone: boolean, el: HTMLElement | null): void {
    if (!open || !el) {
      this.shownEl = null;
      return;
    }
    if (el === this.shownEl) return;
    this.shownEl = el;
    showInTopLayer(el);
    if (phone) return;
    this.place();
    el.classList.add('gad--placed');
    el.focus();
  }

  /** Under the cell, aligned to its start, inside the viewport; above it when there is no room. */
  private place(): void {
    const pop = this.pop()?.nativeElement;
    if (!pop) return;
    const rect = (this.anchor ?? this.host.nativeElement).getBoundingClientRect();
    const { top, left } = placeBelow(rect, pop.getBoundingClientRect(), { gap: GAP, edge: EDGE });
    pop.style.top = `${top}px`;
    pop.style.left = `${left}px`;
  }
}
