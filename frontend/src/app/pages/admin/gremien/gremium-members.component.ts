import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import {
  BadgeComponent,
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DatepickerComponent,
  DialogComponent,
  IconComponent,
  SelectComponent,
  type SelectOption,
} from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import { type DelegationSubstitute, DelegationsApiService } from '@core/api/delegations.service';
import { AdminApiService } from '../admin-api.service';
import type { AdminPrincipal, Gremium, GremiumMembership, GremiumRole } from '../admin.models';

interface Member {
  assignmentId: string;
  name: string;
  email: string | null;
  roleLabel: string;
  term: string;
}

/**
 * Mitglieder eines Gremiums (#18) — eigene **Unterseite** (`/admin/gremien/:id`).
 * Tabelle der Mitglieder; »Mitglied hinzufügen« öffnet einen **Dialog** mit
 * Inline-**Typeahead**-Suche (Vorschläge direkt unter dem Feld, Klick wählt aus).
 */
@Component({
  selector: 'app-gremium-members',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    TranslatePipe,
    ButtonComponent,
    BadgeComponent,
    SelectComponent,
    DatepickerComponent,
    DialogComponent,
    DataTableComponent,
    CellDirective,
    IconComponent,
  ],
  template: `

    <header class="gm__head">
      <div>
        <h1 class="gm__title">{{ 'admin.gremien.membersOf' | t }}: {{ gremium()?.name ?? '…' }}</h1>
        <p class="gm__subtitle">{{ 'admin.gremien.membersHint' | t }}</p>
      </div>
      <app-button size="sm" (click)="openAdd()">{{ 'admin.gremien.addMember' | t }}</app-button>
    </header>

    <app-data-table [columns]="columns()" [rows]="members()" [rowKey]="rowId" [emptyText]="'admin.gremien.membersEmpty' | t">
      <ng-template appCell="email" let-m>{{ $any(m).email || '—' }}</ng-template>
      <ng-template appCell="roleLabel" let-m><app-badge variant="primary">{{ $any(m).roleLabel }}</app-badge></ng-template>
      <ng-template appCell="term" let-m><span class="gm__muted">{{ $any(m).term }}</span></ng-template>
      <ng-template appCell="actions" let-m>
        <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'admin.gremien.memberRemove' | t" (click)="removeMember($any(m).assignmentId)">
          <app-icon name="delete" />
        </app-button>
      </ng-template>
    </app-data-table>

    <!-- Stellvertreter-Pool (#delegation-rework): gewählte/bestimmte Vertreter, an die
         ohne Vorlauf-Deadline (bis Sitzungsbeginn) delegiert werden darf — auch wenn
         sie nicht selbst Mitglied sind (z. B. Fachschafts-Vertreter). -->
    <section class="gm__pool" [attr.aria-label]="'admin.substitutes.title' | t">
      <header class="gm__head">
        <div>
          <h2 class="gm__title">{{ 'admin.substitutes.title' | t }}</h2>
          <p class="gm__subtitle">{{ 'admin.substitutes.hint' | t }}</p>
        </div>
        <app-button size="sm" (click)="openAddSub()">{{ 'admin.substitutes.add' | t }}</app-button>
      </header>
      <app-data-table
        [columns]="subColumns()"
        [rows]="substitutes()"
        [rowKey]="subRowId"
        [emptyText]="'admin.substitutes.empty' | t"
      >
        <ng-template appCell="substitute" let-s>{{ $any(s).substituteName || $any(s).substituteId }}</ng-template>
        <ng-template appCell="member" let-s>
          @if ($any(s).memberId) {
            {{ $any(s).memberName || $any(s).memberId }}
          } @else {
            <span class="gm__muted">{{ 'admin.substitutes.allMembers' | t }}</span>
          }
        </ng-template>
        <ng-template appCell="actions" let-s>
          <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'admin.substitutes.remove' | t" (click)="removeSub($any(s).id)">
            <app-icon name="delete" />
          </app-button>
        </ng-template>
      </app-data-table>
    </section>

    <!-- Stellvertreter hinzufügen: Dialog mit Typeahead (beliebige Nutzer). -->
    <app-dialog
      [open]="addSubOpen()"
      [title]="'admin.substitutes.add' | t"
      [closeLabel]="'admin.gremien.cancel' | t"
      (closed)="addSubOpen.set(false)"
    >
      <div class="gm__add">
        <div class="gm__typeahead">
          <label class="gm__lbl" for="gm-sub-search">{{ 'admin.substitutes.search' | t }}</label>
          <input
            id="gm-sub-search"
            class="gm__control"
            autocomplete="off"
            [placeholder]="'admin.gremien.memberSearchPlaceholder' | t"
            [ngModel]="subQuery()"
            (ngModelChange)="onSubSearch($event)"
            (focus)="onSubSearch(subQuery())"
          />
          @if (subCandidates().length) {
            <ul class="gm__suggest" role="listbox">
              @for (c of subCandidates(); track c.id) {
                <li>
                  <button type="button" class="gm__suggest-item" [class.gm__suggest-item--sel]="subSelected()?.id === c.id" (click)="pickSub(c)">
                    <span class="gm__suggest-name">{{ c.displayName || c.email || c.sub }}</span>
                    @if (c.email) { <span class="gm__suggest-meta">{{ c.email }}</span> }
                  </button>
                </li>
              }
            </ul>
          }
        </div>
        @if (subSelected(); as s) {
          <p class="gm__picked">{{ 'admin.gremien.memberPicked' | t }}: <strong>{{ s.displayName || s.email || s.sub }}</strong></p>
        }
        <app-select
          [label]="'admin.substitutes.forMember' | t"
          [options]="memberOptions()"
          [ngModel]="subMemberId()"
          (ngModelChange)="subMemberId.set($event)"
          name="subMember"
        />
      </div>
      <div dialog-footer class="gm__dialog-foot">
        <app-button variant="ghost" (click)="addSubOpen.set(false)">{{ 'admin.gremien.cancel' | t }}</app-button>
        <app-button [disabled]="!subSelected()" (click)="addSub()">{{ 'admin.substitutes.addAction' | t }}</app-button>
      </div>
    </app-dialog>

    <!-- Mitglied hinzufügen: Dialog mit Typeahead -->
    <app-dialog
      [open]="addOpen()"
      [title]="'admin.gremien.addMember' | t"
      [closeLabel]="'admin.gremien.cancel' | t"
      (closed)="closeAdd()"
    >
      <div class="gm__add">
        <div class="gm__typeahead">
          <label class="gm__lbl" for="gm-search">{{ 'admin.gremien.memberSearch' | t }}</label>
          <input
            id="gm-search"
            class="gm__control"
            autocomplete="off"
            [placeholder]="'admin.gremien.memberSearchPlaceholder' | t"
            [ngModel]="query()"
            (ngModelChange)="onSearch($event)"
            (focus)="onSearch(query())"
          />
          @if (candidates().length) {
            <ul class="gm__suggest" role="listbox">
              @for (c of candidates(); track c.id) {
                <li>
                  <button type="button" class="gm__suggest-item" [class.gm__suggest-item--sel]="selected()?.id === c.id" (click)="pick(c)">
                    <span class="gm__suggest-name">{{ c.displayName || c.email || c.sub }}</span>
                    @if (c.email) { <span class="gm__suggest-meta">{{ c.email }}</span> }
                  </button>
                </li>
              }
            </ul>
          }
        </div>

        @if (selected(); as s) {
          <p class="gm__picked">{{ 'admin.gremien.memberPicked' | t }}: <strong>{{ s.displayName || s.email || s.sub }}</strong></p>
        }

        <app-select
          [label]="'admin.gremien.memberRole' | t"
          [placeholder]="'admin.gremien.memberRolePlaceholder' | t"
          [options]="roleOptions()"
          [ngModel]="addRoleId()"
          (ngModelChange)="addRoleId.set($event)"
          name="memberRole"
        />
        @if (roleOptions().length === 0) {
          <p class="gm__picked">
            {{ 'admin.gremiumRoles.empty' | t }}
            <a [routerLink]="['/admin/gremien', gremiumIdRef, 'roles']">{{ 'admin.gremiumRoles.manage' | t }}</a>
          </p>
        }
        <div class="gm__term">
          <label class="gm__lbl">{{ 'admin.gremien.termFrom' | t }}
            <app-datepicker [ngModel]="addFrom()" (ngModelChange)="addFrom.set($event)" name="from" /></label>
          <label class="gm__lbl">{{ 'admin.gremien.termUntil' | t }}
            <app-datepicker [ngModel]="addUntil()" (ngModelChange)="addUntil.set($event)" name="until" /></label>
        </div>
      </div>
      <div dialog-footer class="gm__dialog-foot">
        <app-button variant="ghost" (click)="closeAdd()">{{ 'admin.gremien.cancel' | t }}</app-button>
        <app-button [disabled]="!selected() || !addRoleId()" (click)="addMember()">{{ 'admin.gremien.memberAdd' | t }}</app-button>
      </div>
    </app-dialog>
  `,
  styles: [
    `
      :host {
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
      }
      .gm__head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-4);
        flex-wrap: wrap;
      }
      .gm__title {
        margin: 0;
      }
      .gm__subtitle {
        color: var(--color-text-muted);
        margin: var(--space-1) 0 0;
      }
      .gm__status {
        color: var(--color-text-muted);
        padding: var(--space-4) 0;
      }
      .gm__table {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--fs-sm);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        overflow: hidden;
      }
      .gm__table th {
        text-align: start;
        padding: var(--space-3) var(--space-4);
        font-size: var(--fs-xs);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--color-text-muted);
        background: var(--color-surface-sunken);
        border-bottom: var(--border-width) solid var(--color-border);
      }
      .gm__table td {
        padding: var(--space-3) var(--space-4);
        border-bottom: var(--border-width) solid var(--color-border);
      }
      .gm__th-actions {
        text-align: end;
      }
      .gm__add {
        display: flex;
        flex-direction: column;
        gap: var(--space-4);
      }
      .gm__typeahead {
        position: relative;
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
      }
      .gm__lbl {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
      }
      .gm__control {
        height: var(--control-height);
        padding: 0 var(--space-3);
        background: var(--color-surface);
        color: var(--color-text);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        font-size: var(--fs-md);
      }
      .gm__suggest {
        list-style: none;
        margin: var(--space-1) 0 0;
        padding: var(--space-1);
        max-height: 14rem;
        overflow-y: auto;
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        box-shadow: var(--shadow-sm);
      }
      .gm__suggest-item {
        display: flex;
        flex-direction: column;
        width: 100%;
        gap: 2px;
        padding: var(--space-2) var(--space-3);
        background: transparent;
        border: 0;
        border-radius: var(--radius-sm);
        cursor: pointer;
        text-align: start;
        color: var(--color-text);
      }
      .gm__suggest-item:hover,
      .gm__suggest-item--sel {
        background: var(--color-surface-sunken);
      }
      .gm__suggest-name {
        font-weight: var(--fw-medium);
      }
      .gm__suggest-meta {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
      }
      .gm__picked {
        margin: 0;
        font-size: var(--fs-sm);
      }
      .gm__muted {
        color: var(--color-text-muted);
        font-size: var(--fs-sm);
      }
      .gm__term {
        display: flex;
        gap: var(--space-3);
      }
      .gm__term .gm__lbl {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
        flex: 1;
      }
      .gm__dialog-foot {
        display: flex;
        gap: var(--space-3);
      }
      /* Mobil (≤768px): Amtszeit-Datepicker untereinander statt nebeneinander. */
      @media (max-width: 768px) {
        .gm__term {
          flex-direction: column;
        }
      }
    `,
  ],
})
export class GremiumMembersComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly route = inject(ActivatedRoute);

  private readonly gremiumId = this.route.snapshot.paramMap.get('id') ?? '';
  protected readonly gremiumIdRef = this.gremiumId;

  readonly gremium = signal<Gremium | null>(null);
  private readonly principalsById = signal<Map<string, AdminPrincipal>>(new Map());
  private readonly gremiumRoles = signal<GremiumRole[]>([]);
  private readonly memberships = signal<GremiumMembership[]>([]);

  readonly addOpen = signal(false);
  readonly query = signal('');
  readonly candidates = signal<AdminPrincipal[]>([]);
  readonly selected = signal<AdminPrincipal | null>(null);
  readonly addRoleId = signal('');
  readonly addFrom = signal('');
  readonly addUntil = signal('');

  readonly roleOptions = computed<SelectOption[]>(() =>
    this.gremiumRoles().map((r) => ({ value: r.id, label: this.roleName(r) })),
  );

  readonly columns = computed<ColumnDef[]>(() => [
    { key: 'name', label: this.i18n.translate('admin.users.col.name') },
    { key: 'email', label: this.i18n.translate('admin.users.col.email') },
    { key: 'roleLabel', label: this.i18n.translate('admin.gremien.memberRole') },
    { key: 'term', label: this.i18n.translate('admin.gremien.term') },
    { key: 'actions', label: this.i18n.translate('admin.users.col.actions'), align: 'end' },
  ]);
  readonly rowId = (m: unknown): string => (m as Member).assignmentId;

  readonly members = computed<Member[]>(() => {
    const rolesById = new Map(this.gremiumRoles().map((r) => [r.id, r]));
    const byId = this.principalsById();
    return this.memberships().map((m) => {
      const p = byId.get(m.principalId);
      const role = rolesById.get(m.gremiumRoleId);
      return {
        assignmentId: m.id,
        name: p ? p.displayName || p.email || p.sub : m.principalId,
        email: p?.email ?? null,
        roleLabel: role ? this.roleName(role) : m.gremiumRoleId,
        term: this.term(m),
      };
    });
  });

  // --- Stellvertreter-Pool (#delegation-rework) -----------------------------
  private readonly delegationsApi = inject(DelegationsApiService);
  readonly substitutes = signal<DelegationSubstitute[]>([]);
  readonly addSubOpen = signal(false);
  readonly subQuery = signal('');
  readonly subCandidates = signal<AdminPrincipal[]>([]);
  readonly subSelected = signal<AdminPrincipal | null>(null);
  /** '' = gremium-weiter Stellvertreter (vertritt jedes Mitglied). */
  readonly subMemberId = signal('');

  readonly subColumns = computed<ColumnDef[]>(() => [
    { key: 'substitute', label: this.i18n.translate('admin.substitutes.col.substitute') },
    { key: 'member', label: this.i18n.translate('admin.substitutes.col.member') },
    { key: 'actions', label: this.i18n.translate('admin.users.col.actions'), align: 'end' },
  ]);
  readonly subRowId = (s: unknown): string => (s as DelegationSubstitute).id;

  /** Empfänger-Auswahl »vertritt«: alle Mitglieder oder ein konkretes. */
  readonly memberOptions = computed<SelectOption[]>(() => {
    const byId = this.principalsById();
    const seen = new Set<string>();
    const opts: SelectOption[] = [
      { value: '', label: this.i18n.translate('admin.substitutes.allMembers') },
    ];
    for (const m of this.memberships()) {
      if (seen.has(m.principalId)) continue;
      seen.add(m.principalId);
      const p = byId.get(m.principalId);
      opts.push({ value: m.principalId, label: p ? p.displayName || p.email || p.sub : m.principalId });
    }
    return opts;
  });

  constructor() {
    this.api
      .listGremien()
      .pipe(takeUntilDestroyed())
      .subscribe((list) => this.gremium.set(list.find((g) => g.id === this.gremiumId) ?? null));
    this.api.listGremiumRoles(this.gremiumId as Uuid).subscribe({
      next: (r) => this.gremiumRoles.set(r),
      error: () => this.gremiumRoles.set([]),
    });
    // Principal-Namen für die Anzeige (id → Principal).
    this.api.listPrincipals('').subscribe({
      next: (p) => this.principalsById.set(new Map(p.map((x) => [x.id, x]))),
      error: () => this.principalsById.set(new Map()),
    });
    this.refresh();
    this.refreshSubstitutes();
  }

  openAddSub(): void {
    this.subQuery.set('');
    this.subSelected.set(null);
    this.subCandidates.set([]);
    this.subMemberId.set('');
    this.addSubOpen.set(true);
  }

  onSubSearch(q: string): void {
    this.subQuery.set(q);
    this.api.listPrincipals(q).subscribe({
      next: (list) => this.subCandidates.set(list.slice(0, 8)),
      error: () => this.subCandidates.set([]),
    });
  }

  pickSub(c: AdminPrincipal): void {
    this.subSelected.set(c);
    this.subQuery.set(c.displayName || c.email || c.sub);
    this.subCandidates.set([]);
  }

  addSub(): void {
    const s = this.subSelected();
    if (!s) return;
    this.delegationsApi
      .addSubstitute({
        gremiumId: this.gremiumId as Uuid,
        memberId: this.subMemberId() ? (this.subMemberId() as Uuid) : null,
        substituteId: s.id,
      })
      .subscribe({
        next: () => {
          this.toast.success(this.i18n.translate('admin.substitutes.added'));
          this.addSubOpen.set(false);
          this.refreshSubstitutes();
        },
        error: (err: { status?: number }) =>
          this.toast.error(
            this.i18n.translate(
              err.status === 409 ? 'admin.substitutes.duplicate' : 'admin.substitutes.failed',
            ),
          ),
      });
  }

  removeSub(id: string): void {
    this.delegationsApi.removeSubstitute(id as Uuid).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('admin.substitutes.removed'));
        this.refreshSubstitutes();
      },
      error: () => this.toast.error(this.i18n.translate('admin.substitutes.failed')),
    });
  }

  private refreshSubstitutes(): void {
    this.delegationsApi.substitutes(this.gremiumId as Uuid).subscribe({
      next: (list) => this.substitutes.set(list),
      error: () => this.substitutes.set([]),
    });
  }

  private roleName(role: GremiumRole): string {
    return role.name[this.i18n.locale()] ?? role.name['de'] ?? role.key;
  }

  private term(m: GremiumMembership): string {
    const f = m.validFrom ? m.validFrom.slice(0, 10) : '';
    const u = m.validUntil ? m.validUntil.slice(0, 10) : '';
    if (!f && !u) return '—';
    return `${f || '…'} – ${u || '…'}`;
  }

  openAdd(): void {
    this.query.set('');
    this.selected.set(null);
    this.addRoleId.set('');
    this.addFrom.set('');
    this.addUntil.set('');
    this.candidates.set([]);
    this.addOpen.set(true);
  }

  closeAdd(): void {
    this.addOpen.set(false);
  }

  onSearch(q: string): void {
    this.query.set(q);
    this.api.listPrincipals(q).subscribe({
      next: (list) => this.candidates.set(list.slice(0, 8)),
      error: () => this.candidates.set([]),
    });
  }

  pick(c: AdminPrincipal): void {
    this.selected.set(c);
    this.query.set(c.displayName || c.email || c.sub);
    this.candidates.set([]);
  }

  addMember(): void {
    const s = this.selected();
    const roleId = this.addRoleId();
    if (!s || !roleId) return;
    this.api
      .createGremiumMembership(this.gremiumId as Uuid, {
        principalId: s.id,
        gremiumRoleId: roleId as Uuid,
        validFrom: this.addFrom() || null,
        validUntil: this.addUntil() || null,
      })
      .subscribe({
        next: () => {
          this.toast.success(this.i18n.translate('admin.gremien.memberAdded'));
          this.addOpen.set(false);
          this.refresh();
        },
        // 409 = überlappende Amtszeit (eine Rolle je Zeitpunkt).
        error: (err: { status?: number }) =>
          this.toast.error(
            this.i18n.translate(
              err.status === 409 ? 'admin.gremien.memberOverlap' : 'admin.gremien.memberFailed',
            ),
          ),
      });
  }

  removeMember(membershipId: string): void {
    this.api.deleteGremiumMembership(membershipId as Uuid).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('admin.gremien.memberRemoved'));
        this.refresh();
      },
      error: () => this.toast.error(this.i18n.translate('admin.gremien.memberFailed')),
    });
  }

  private refresh(): void {
    this.api.listGremiumMemberships(this.gremiumId as Uuid).subscribe({
      next: (m) => this.memberships.set(m),
      // Kein stilles Schlucken mehr (#5-3): 403/Fehler sichtbar machen statt leerer Tabelle.
      error: () => {
        this.memberships.set([]);
        this.toast.error(this.i18n.translate('admin.gremien.membersLoadFailed'));
      },
    });
  }
}
