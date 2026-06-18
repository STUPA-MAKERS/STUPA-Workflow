import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { catchError, of } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { type Delegation, DelegationsApiService } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { ApplicationListItem, ApplicationType, Meeting, Uuid } from '@core/api/models';
import { BadgeComponent } from '@shared/ui/badge/badge.component';
import { CapitalizePipe } from '@shared/pipes/capitalize.pipe';

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
  imports: [RouterLink, LocalizedDatePipe, TranslatePipe, BadgeComponent, CapitalizePipe],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent {
  readonly auth = inject(AuthService);
  private readonly api = inject(ApiClient);

  /** „Meine Anträge": ausschließlich die EIGENEN Anträge — `mine=true` erzwingt
   *  den Owner-Filter auch für Principals mit `application.read` (sonst zeigte
   *  die Karte Berechtigten alle Anträge). */
  private readonly applications = toSignal(
    this.api.listApplications({ mine: true }).pipe(catchError(() => of(null))),
    { initialValue: undefined },
  );

  /** „Offene Aufgaben": echte offene Entscheidungen (GET /applications/tasks). */
  private readonly tasks = toSignal(
    this.api.listTasks().pipe(catchError(() => of([] as ApplicationListItem[]))),
    { initialValue: [] as ApplicationListItem[] },
  );

  private readonly types = toSignal(
    this.api.applicationTypes({ quiet: true }).pipe(catchError(() => of([] as ApplicationType[]))),
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

  /** Offene Aufgaben: Anträge mit einer für mich offenen Entscheidung. */
  readonly openTasks = computed(() => this.tasks());

  readonly taskRows = computed(() => this.openTasks().slice(0, PREVIEW_ROWS));
  readonly applicationRows = computed(() => this.items().slice(0, PREVIEW_ROWS));

  name(item: ApplicationListItem): string {
    return this.typeName()(item.typeId);
  }

  /** Antragstitel (System-Titelfeld) mit Fallback auf den Antragstyp. */
  titleOf(item: ApplicationListItem): string {
    return item.title?.trim() || this.typeName()(item.typeId);
  }

  created(item: ApplicationListItem): string | null {
    return item.createdAt ?? null;
  }

  /** Antrags-Panels nur, wenn der Nutzer Anträge lesen darf. */
  readonly canReadApplications = computed(() => this.auth.canAny('application.read'));

  // --- Sitzungs-Shortcuts: laufende/anstehende Sitzungen prominent (#Sessions) ---
  private readonly meetings = toSignal(
    this.api.listMeetings().pipe(catchError(() => of([] as Meeting[]))),
    { initialValue: [] as Meeting[] },
  );
  /** Laufende zuerst, dann geplante (nächste Termine), max. 4 — große Shortcuts. */
  readonly sessionShortcuts = computed<Meeting[]>(() => {
    const rank = (m: Meeting): number => (m.status === 'live' ? 0 : m.status === 'planned' ? 1 : 2);
    return this.meetings()
      .filter((m) => m.status !== 'closed')
      .slice()
      .sort((a, b) => rank(a) - rank(b) || (a.date ?? '').localeCompare(b.date ?? ''))
      .slice(0, 4);
  });

  sessionStatusKey(status: Meeting['status']): TranslationKey {
    return `meetings.status.${status}` as TranslationKey;
  }

  sessionVariant(status: Meeting['status']): 'success' | 'info' | 'neutral' {
    return status === 'live' ? 'success' : status === 'planned' ? 'info' : 'neutral';
  }

  private readonly i18n = inject(I18nService);
  /** Rollen-Key lokalisiert (admin→Administrator …); unbekannt → roher Key. */
  roleLabel(role: string): string {
    const key = `role.${role}`;
    const label = this.i18n.translate(key as TranslationKey);
    return label === key ? role : label;
  }

  /** Globale Rollen des Nutzers (Badges, #54). */
  readonly roles = computed(() => this.auth.roles());
  /** Gremien-Zugehörigkeiten des Nutzers (Badges, #54). */
  readonly gremien = computed(() => this.auth.gremien());

  // --- Vertretung/Delegation (#delegation-rework): aktive Sitzungs-Vertretungen ---
  private readonly delegationsApi = inject(DelegationsApiService);
  private readonly delegationsRaw = toSignal(
    this.delegationsApi.list().pipe(catchError(() => of([] as Delegation[]))),
    { initialValue: [] as Delegation[] },
  );
  /** Nur Vertretungen kommender/laufender Sitzungen (widerrufbare zuerst). */
  readonly delegations = computed<Delegation[]>(() =>
    this.delegationsRaw()
      .filter((d) => d.revocable)
      .slice(0, PREVIEW_ROWS),
  );

  /** Ausgehend = ich werde vertreten (Richtung liefert der Server). */
  isOutgoing(d: Delegation): boolean {
    return d.direction === 'outgoing';
  }
}
