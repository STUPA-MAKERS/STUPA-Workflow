import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import type { Uuid } from '@core/api/models';
import type { TodoBoardKind, TodoBoardSummary } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { SideSheetComponent } from '@shared/ui/side-sheet/side-sheet.component';
import { IconComponent, MEDIA, type IconName } from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../../layout/media-query';

export const BOARD_ICON: Record<TodoBoardKind, IconName> = {
  personal: 'user',
  gremium: 'landmark',
  team: 'ticket',
};

let nextId = 0;

interface PickerSection {
  kind: TodoBoardKind;
  label: TranslationKey;
  boards: TodoBoardSummary[];
}

/**
 * The board chip of the to-dos page ("Board: Studierendenparlament", frame 34) and its
 * list: Persönlich, Gremien and Team, each board with its open count. Desktop: a list
 * under the chip; Escape and a click outside close it. Phone: the bottom sheet.
 */
@Component({
  selector: 'app-todo-board-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet, TranslatePipe, IconComponent, SideSheetComponent],
  templateUrl: './todo-board-picker.component.html',
  styleUrl: './todo-board-picker.component.scss',
})
export class TodoBoardPickerComponent {
  private readonly i18n = inject(I18nService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);

  readonly boards = input<readonly TodoBoardSummary[]>([]);
  readonly current = input<Uuid | null>(null);
  /** Phone: the chip names the board only. */
  readonly compact = input(false);
  readonly picked = output<Uuid>();

  readonly phone = mediaQuerySignal(MEDIA.phone);
  readonly open = signal(false);
  readonly listId = `todo-board-picker-${nextId++}`;
  private readonly chip = viewChild.required<ElementRef<HTMLButtonElement>>('chip');

  readonly currentBoard = computed(() => this.boards().find((b) => b.id === this.current()) ?? null);
  readonly chipText = computed(() => {
    const b = this.currentBoard();
    if (!b) return this.i18n.translate('todos.board.pick');
    return this.compact() ? b.name : this.i18n.translate('todos.board.chip', { name: b.name });
  });
  readonly chipIcon = computed(() => BOARD_ICON[this.currentBoard()?.kind ?? 'gremium']);

  readonly sections = computed<PickerSection[]>(() => {
    const of = (kind: TodoBoardKind) => this.boards().filter((b) => b.kind === kind);
    const all: PickerSection[] = [
      { kind: 'personal', label: 'todos.board.personal', boards: of('personal') },
      { kind: 'gremium', label: 'todos.board.gremien', boards: of('gremium') },
      { kind: 'team', label: 'todos.board.team', boards: of('team') },
    ];
    return all.filter((s) => s.boards.length);
  });

  constructor() {
    const onPointer = (e: Event) => {
      if (!this.open() || this.phone()) return;
      if (e.target instanceof Node && this.host.nativeElement.contains(e.target)) return;
      this.open.set(false);
    };
    document.addEventListener('pointerdown', onPointer, true);
    inject(DestroyRef).onDestroy(() => document.removeEventListener('pointerdown', onPointer, true));
  }

  icon(kind: TodoBoardKind): IconName {
    return BOARD_ICON[kind];
  }

  sub(board: TodoBoardSummary): string {
    const open = this.i18n.translate('todos.board.open', { n: board.openCount });
    if (board.kind === 'personal') return `${open} · ${this.i18n.translate('todos.board.onlyYou')}`;
    if (board.kind === 'team') return `${open} · ${this.i18n.translate('todos.board.teamSub')}`;
    return open;
  }

  toggle(): void {
    this.open.update((v) => !v);
    if (this.open() && !this.phone()) {
      afterNextRender(
        () => {
          const root = this.host.nativeElement;
          const row =
            root.querySelector<HTMLElement>('.bp__row[aria-current="true"]') ?? root.querySelector<HTMLElement>('.bp__row');
          row?.focus();
        },
        { injector: this.injector },
      );
    }
  }

  pick(board: TodoBoardSummary): void {
    this.open.set(false);
    if (board.id !== this.current()) this.picked.emit(board.id);
    if (!this.phone()) this.chip().nativeElement.focus();
  }

  onKey(event: KeyboardEvent): void {
    if (event.key === 'Escape' && this.open()) {
      event.preventDefault();
      this.open.set(false);
      this.chip().nativeElement.focus();
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    const rows = Array.from(this.host.nativeElement.querySelectorAll<HTMLElement>('.bp__pop .bp__row'));
    if (!rows.length) return;
    event.preventDefault();
    const at = rows.indexOf(document.activeElement as HTMLElement);
    const next = event.key === 'ArrowDown' ? Math.min(rows.length - 1, at + 1) : Math.max(0, at - 1);
    rows[next].focus();
  }
}
