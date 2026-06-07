import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { catchError, of } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { ApplicationListItem, ApplicationType, Uuid } from '@core/api/models';
import { BadgeComponent } from '@shared/ui/badge/badge.component';
import { CardComponent } from '@shared/ui/card/card.component';
import { CapitalizePipe } from '@shared/pipes/capitalize.pipe';
import { stateBadgeVariant } from '../applications/applications.util';

/** Sekundär-Kachel (eigene Zielseite, kein Antrags-Inhalt) — RBAC-gated. */
interface QuickLink {
  readonly permissions: string[];
  readonly titleKey: TranslationKey;
  readonly route: string;
}

/** Wie viele Antrags-Zeilen je Panel maximal gezeigt werden. */
const PREVIEW_ROWS = 5;

/**
 * Rollenbasierte Startseite (overview §4). Drei distinkte Bereiche statt
 * redundanter Zähl-Kacheln:
 *  - **Antrag stellen** – primäre CTA in den Apply-Wizard (`/apply`).
 *  - **Offene Aufgaben** – Anträge, die auf Bearbeitung/Prüfung warten
 *    (nicht-abgeschlossene Status), mit Deep-Link.
 *  - **Meine Anträge** – die (lesbaren) Anträge des Nutzers mit Status + Deep-Link.
 * Darunter RBAC-gegatete Schnellzugriffe (Abstimmungen/Sitzungen/Budget/Verwaltung).
 *
 * Datenquelle ist `GET /applications` (real bei Mock-aus, sonst Mock). Eine
 * applicant-skopierte „nur meine"-Filterung liefert das Backend noch nicht;
 * TODO(wiring): eigenen Filter nutzen, sobald vorhanden.
 */
@Component({
  selector: 'app-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, DatePipe, TranslatePipe, CardComponent, BadgeComponent, CapitalizePipe],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent {
  readonly auth = inject(AuthService);
  private readonly api = inject(ApiClient);

  /** Lesbare/relevante Anträge (Quelle für Aufgaben- und Antrags-Panel). */
  private readonly applications = toSignal(
    this.api.listApplications().pipe(catchError(() => of(null))),
    { initialValue: undefined },
  );

  private readonly types = toSignal(
    this.api.applicationTypes().pipe(catchError(() => of([] as ApplicationType[]))),
    { initialValue: [] as ApplicationType[] },
  );
  private readonly typeName = computed(() => {
    const map = new Map(this.types().map((t) => [t.id, t.name]));
    return (id: Uuid): string => map.get(id) ?? id;
  });

  /** `true`, solange der Antrags-Endpunkt noch nicht geantwortet hat. */
  readonly loading = computed(() => this.applications() === undefined);
  /** `true`, wenn der Antrags-Endpunkt fehlschlug. */
  readonly error = computed(() => this.applications() === null);

  private readonly items = computed<ApplicationListItem[]>(() => this.applications()?.items ?? []);
  readonly total = computed(() => this.applications()?.total ?? 0);

  /** Offene Aufgaben: nicht-abgeschlossene Anträge (warten auf Bearbeitung/Prüfung). */
  readonly openTasks = computed(() =>
    this.items().filter((a) => a.state?.category && a.state.category !== 'closed'),
  );

  readonly taskRows = computed(() => this.openTasks().slice(0, PREVIEW_ROWS));
  readonly applicationRows = computed(() => this.items().slice(0, PREVIEW_ROWS));

  readonly stateVariant = stateBadgeVariant;

  name(item: ApplicationListItem): string {
    return this.typeName()(item.typeId);
  }

  created(item: ApplicationListItem): string | null {
    return item.createdAt ?? null;
  }

  // --- Schnellzugriffe (distinkte Ziele, kein Antrags-Inhalt) ---------------
  private readonly quickLinks: QuickLink[] = [
    { permissions: ['vote.cast', 'vote.manage'], titleKey: 'dashboard.votes.title', route: '/voting' },
    { permissions: ['meeting.manage', 'protocol.write'], titleKey: 'dashboard.meetings.title', route: '/meetings' },
    { permissions: ['budget.view', 'budget.manage'], titleKey: 'dashboard.budget.title', route: '/budget' },
    { permissions: ['admin.config'], titleKey: 'dashboard.admin.title', route: '/admin' },
  ];

  readonly visibleQuickLinks = computed(() =>
    this.quickLinks.filter((q) => this.auth.canAny(...q.permissions)),
  );

  /** Antrags-Panels nur, wenn der Nutzer Anträge lesen darf. */
  readonly canReadApplications = computed(() => this.auth.canAny('application.read'));
}
