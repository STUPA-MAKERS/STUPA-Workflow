import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { NavKey } from '../nav.service';
import { RailStatusService } from '../rail-status.service';

/** The highest count the badge spells out; above it shows "99+". */
const MAX_COUNT = 99;

/**
 * The mark on a navigation icon: the number of open tasks on "Aufgaben" and a dot on
 * "Sitzungen" while a meeting runs. Other entries carry no mark.
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

  readonly key = input.required<NavKey>();
  /**
   * `visual`: the badge or the dot, hidden from screen readers; it sits on the icon.
   * `text`: the same information as hidden text; it goes after the label, so the link
   * reads "Aufgaben 8 offen" and not "8 offen Aufgaben".
   */
  readonly part = input<'visual' | 'text'>('visual');

  /** The task count to show; 0 shows no badge. */
  readonly count = computed(() => (this.key() === 'tasks' ? (this.status.taskCount() ?? 0) : 0));

  readonly countLabel = computed(() => {
    const n = this.count();
    return n > MAX_COUNT ? `${MAX_COUNT}+` : String(n);
  });

  readonly live = computed(() => this.key() === 'meetings' && this.status.live());
}
