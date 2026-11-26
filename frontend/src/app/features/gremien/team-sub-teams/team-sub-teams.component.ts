import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { Router } from '@angular/router';
import type { Uuid } from '@core/api/models';
import type { TeamDetail } from '@core/api/teams.service';
import { I18nService } from '@core/i18n/i18n.service';
import type { Action, ListRow, LoadState } from '@stupa-makers/ui-kit';
import { RecordSectionComponent } from '@stupa-makers/ui-kit/screens';
import { GremienStore } from '../gremien.store';
import { TeamNameDialogComponent } from '../team-name-dialog/team-name-dialog.component';

/**
 * The tab "Sub-Teams" of a team (spec 003062): its sub-teams by name, each a link to its
 * page, and for a manager of the team the action "Sub-Team anlegen" (spec 003065). The list
 * comes from the store of the tab, so it needs no request of its own. The kit record section
 * draws the heading with the action, the rows and the empty face.
 */
@Component({
  selector: 'app-team-sub-teams',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RecordSectionComponent, TeamNameDialogComponent],
  template: `
    <app-record-section
      [level]="3"
      [heading]="i18n.translate('gremien.tab.subTeams')"
      [rows]="rows()"
      [actions]="actions()"
      (action)="createOpen.set(true)"
    />
    <app-team-name-dialog [(open)]="createOpen" [parentId]="teamId()" (saved)="created($event)" />
  `,
})
export class TeamSubTeamsComponent {
  private readonly store = inject(GremienStore);
  private readonly router = inject(Router);
  protected readonly i18n = inject(I18nService);

  readonly teamId = input.required<Uuid>();
  readonly canManage = input(false);

  readonly createOpen = signal(false);
  readonly subTeams = computed(() => this.store.subTeams(this.teamId()));

  readonly actions = computed<readonly Action[]>(() =>
    this.canManage() ? [{ key: 'create', label: this.i18n.translate('teams.createSub'), icon: 'plus' }] : [],
  );

  readonly rows = computed<LoadState<readonly ListRow[]>>(() => {
    const subs = this.subTeams();
    if (!subs.length) return { state: 'empty', icon: 'users', heading: this.i18n.translate('teams.subTeams.empty') };
    return {
      state: 'ready',
      data: subs.map((sub) => ({
        id: sub.id,
        title: sub.name,
        link: { commands: ['/teams', sub.id] },
      })),
    };
  });

  created(detail: TeamDetail): void {
    this.store.reloadTeams();
    void this.router.navigate(['/teams', detail.team.id]);
  }
}
