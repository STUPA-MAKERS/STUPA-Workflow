import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { RailStatusService } from '../rail-status.service';

/** The highest count the badge spells out; above it shows "99+". */
const MAX_COUNT = 99;

/**
 * The mark on a navigation icon: the number of open tasks on "Aufgaben", the number of
 * new tickets on "Tickets" and a dot on "Sitzungen" while a meeting runs. Other entries
 * carry no mark.
 *
 * Use it twice per entry: `part="visual"` on the icon and `part="text"` after the label.
 */
@Component({
  selector: 'app-nav-mark',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe],
  templateUrl: './nav-mark.component.html',
  styleUrl: './nav-mark.component.scss',
})
export class NavMarkComponent {
  private readonly status = inject(RailStatusService);

  /** The key of the navigation entry (`NavKey`). */
  readonly key = input.required<string>();
  /**
   * `visual`: the badge or the dot, hidden from screen readers; it sits on the icon.
   * `text`: the same information as hidden text; it goes after the label, so the link
   * reads "Aufgaben 8 offen" and not "8 offen Aufgaben".
   * `count`: the count alone as a badge in the flow, at the end of a row of the "Mehr"
   * sheet; hidden from screen readers like `visual`.
   */
  readonly part = input<'visual' | 'text' | 'count'>('visual');

  /** The count to show; 0 shows no badge. */
  readonly count = computed(() => {
    switch (this.key()) {
      case 'tasks':
        return this.status.taskCount() ?? 0;
      case 'tickets':
        return this.status.ticketCount() ?? 0;
      default:
        return 0;
    }
  });

  /** The hidden text of the count: "8 offen", or "2 neu" for the tickets. */
  readonly countText = computed<TranslationKey>(() =>
    this.key() === 'tickets' ? 'shell.nav.ticketsNew' : 'shell.nav.tasksOpen',
  );

  readonly countLabel = computed(() => {
    const n = this.count();
    return n > MAX_COUNT ? `${MAX_COUNT}+` : String(n);
  });

  readonly live = computed(() => this.key() === 'meetings' && this.status.live());
}
