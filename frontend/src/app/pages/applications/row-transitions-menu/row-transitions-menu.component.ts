import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import type { ApplicationListItem, Transition } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { RowMenuComponent, type RowMenuItem, type RowMenuSection } from '@shared/ui';
import { isRejection } from '../applications.util';

/** What the reader chose in the row menu. The list page carries it out. */
export type RowAction =
  | { kind: 'open' }
  | { kind: 'share' }
  | { kind: 'archive' }
  | { kind: 'force' }
  | { kind: 'delete' }
  | { kind: 'transition'; transition: Transition };

/**
 * The "more" menu of one row of the applications list.
 *
 * "Übergänge" load only when the menu opens (`GET /applications/{id}/transitions`), so a
 * list of fifty rows makes no fifty requests. Then: Öffnen, Öffentliche Links, Archivieren
 * or Aus Archiv holen, Status setzen, and Löschen in red. Each item shows only with its
 * permission; the server checks again.
 */
@Component({
  selector: 'app-row-transitions-menu',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RowMenuComponent],
  templateUrl: './row-transitions-menu.component.html',
  styleUrl: './row-transitions-menu.component.scss',
})
export class RowTransitionsMenuComponent {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);

  readonly item = input.required<ApplicationListItem>();
  /** The title of the row, for the name of the button. */
  readonly title = input.required<string>();

  readonly action = output<RowAction>();

  /** The transitions are on their way; the menu draws its placeholder. */
  protected readonly pending = signal(false);
  private readonly transitions = signal<Transition[]>([]);
  private seq = 0;

  private readonly canTransition = computed(() => this.auth.can('application.transition'));

  protected readonly label = computed(() =>
    this.i18n.translate('applications.row.menu', { title: this.title() }),
  );

  protected readonly sections = computed<RowMenuSection[]>(() => {
    const t = (key: Parameters<I18nService['translate']>[0]) => this.i18n.translate(key);
    const transitions: RowMenuItem[] = this.transitions().map((tr) => ({
      id: `t:${tr.id}`,
      label: tr.label || t('applications.transitions.fallback'),
      icon: isRejection(tr) ? 'x' : tr.addsToAgenda ? 'cal' : 'play',
      danger: isRejection(tr),
    }));
    const actions: RowMenuItem[] = [{ id: 'open', label: t('applications.row.open'), icon: 'ext' }];
    if (this.auth.can('application.share')) {
      actions.push({ id: 'share', label: t('applications.row.share'), icon: 'link' });
    }
    if (this.auth.can('application.archive')) {
      const archived = this.item().archivedAt !== null;
      actions.push({
        id: 'archive',
        label: t(archived ? 'applications.row.unarchive' : 'applications.row.archive'),
        icon: 'archive',
      });
    }
    if (this.auth.can('application.force_status')) {
      actions.push({ id: 'force', label: t('applications.detail.forceStatus'), icon: 'flow' });
    }
    const danger: RowMenuItem[] = this.auth.can('application.delete')
      ? [{ id: 'delete', label: t('applications.detail.delete'), icon: 'trash', danger: true }]
      : [];
    return [
      { label: t('applications.transitions.title'), items: transitions },
      { items: actions },
      { items: danger },
    ];
  });

  /** The menu opened: load the transitions of this row afresh. */
  protected onOpened(): void {
    this.transitions.set([]);
    if (!this.canTransition()) return;
    const seq = ++this.seq;
    this.pending.set(true);
    this.api.transitions(this.item().id).subscribe({
      next: (list) => {
        if (seq !== this.seq) return;
        this.transitions.set(list);
        this.pending.set(false);
      },
      error: () => {
        if (seq !== this.seq) return;
        this.transitions.set([]);
        this.pending.set(false);
      },
    });
  }

  protected onSelected(item: RowMenuItem): void {
    if (item.id.startsWith('t:')) {
      const transition = this.transitions().find((tr) => `t:${tr.id}` === item.id);
      if (transition) this.action.emit({ kind: 'transition', transition });
      return;
    }
    this.action.emit({ kind: item.id as Exclude<RowAction['kind'], 'transition'> } as RowAction);
  }
}
