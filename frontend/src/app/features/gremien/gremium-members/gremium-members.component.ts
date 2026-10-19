import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
} from '@angular/core';
import type { Subscription } from 'rxjs';
import { GremienApiService, type GremiumMember } from '@core/api/gremien.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { downloadBlob } from '@shared/download.util';
import { AvatarComponent } from '@shared/ui/avatar/avatar.component';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import {
  FilterSelectComponent,
  type FilterSelectOption,
} from '@shared/ui/filter-select/filter-select.component';
import { SearchPillComponent } from '@shared/ui/search-pill/search-pill.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { ButtonComponent, IconComponent, MEDIA, mediaQuery } from '@stupa-makers/ui-kit';
import { fileSlug, localized, roleRank, toCsv } from '../gremien.util';
import { dayMonthYear } from '@shared/date-format';
import { StickyBarComponent } from '@shared/ui/sticky-bar/sticky-bar.component';
import { NoteComponent } from '@shared/ui/note/note.component';
import { personLabel } from '@shared/person-label.util';

export interface MemberGroup {
  readonly key: string;
  readonly label: string;
  readonly rows: readonly MemberRow[];
}

export interface MemberRow {
  readonly member: GremiumMember;
  readonly name: string;
  readonly period: string;
}

/**
 * The sub-tab "Mitglieder" of a gremium: the members grouped by role (Vorstand, Manager,
 * the own roles of the gremium, Mitglied), each with the term of the membership and the
 * e-mail address. The address is never cut: it wraps.
 *
 * The search and the chip "Rolle" filter in the browser. The chip "Ehemalige" reads the
 * memberships whose term has ended. "Als CSV exportieren" saves what the list shows.
 * The attendance is in the tab "Anwesenheit" only.
 */
@Component({
  selector: 'app-gremium-members',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NoteComponent,
    StickyBarComponent,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    AvatarComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    SearchPillComponent,
    SkeletonComponent,
  ],
  templateUrl: './gremium-members.component.html',
  styleUrl: './gremium-members.component.scss',
})
export class GremiumMembersComponent {
  private readonly api = inject(GremienApiService);
  private readonly i18n = inject(I18nService);

  readonly gremiumId = input.required<string>();
  /** The name of the gremium, for the file name of the export. */
  readonly gremiumName = input('');

  readonly phone = mediaQuery(MEDIA.phone);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly members = signal<readonly GremiumMember[]>([]);
  readonly former = signal(false);
  readonly role = signal('');
  readonly query = signal('');
  private sub: Subscription | null = null;

  readonly formerOptions = computed<FilterSelectOption[]>(() => [
    { value: '', label: this.i18n.translate('gremien.members.currentOption') },
    { value: 'former', label: this.i18n.translate('gremien.members.formerOption') },
  ]);

  /** The roles of the loaded members, in role order. */
  readonly roleOptions = computed<FilterSelectOption[]>(() => {
    const locale = this.i18n.locale();
    const roles = new Map<string, string>();
    for (const m of this.sorted()) {
      if (!roles.has(m.member.roleKey)) roles.set(m.member.roleKey, localized(m.member.roleName, locale, m.member.roleKey));
    }
    return [
      { value: '', label: this.i18n.translate('gremien.members.roleAll') },
      ...[...roles].map(([value, label]) => ({ value, label })),
    ];
  });
  readonly roleText = computed(() => {
    const role = this.role();
    if (!role) return null;
    const label = this.roleOptions().find((o) => o.value === role)?.label ?? role;
    return `${this.i18n.translate('gremien.members.role')}: ${label}`;
  });

  readonly searchPlaceholder = computed(() =>
    this.i18n.translate('gremien.members.search', { n: this.members().length }),
  );

  /** Every member in role order, then by name. */
  private readonly sorted = computed<MemberRow[]>(() => {
    const locale = this.i18n.locale();
    return this.members()
      .map((member) => ({ member, name: personLabel(member, this.i18n, { fallbackText: '—' }), period: this.period(member) }))
      .sort(
        (a, b) =>
          roleRank(a.member.roleKey) - roleRank(b.member.roleKey) ||
          a.member.roleKey.localeCompare(b.member.roleKey) ||
          a.name.localeCompare(b.name, locale),
      );
  });

  private readonly visible = computed<MemberRow[]>(() => {
    const role = this.role();
    const q = this.query().trim().toLocaleLowerCase(this.i18n.locale());
    return this.sorted().filter(
      (r) =>
        (!role || r.member.roleKey === role) &&
        (!q ||
          r.name.toLocaleLowerCase(this.i18n.locale()).includes(q) ||
          (r.member.email ?? '').toLocaleLowerCase().includes(q)),
    );
  });

  readonly groups = computed<MemberGroup[]>(() => {
    const locale = this.i18n.locale();
    const out: { key: string; label: string; rows: MemberRow[] }[] = [];
    for (const row of this.visible()) {
      const key = row.member.roleKey;
      let group = out.find((g) => g.key === key);
      if (!group) {
        group = { key, label: localized(row.member.roleName, locale, key), rows: [] };
        out.push(group);
      }
      group.rows.push(row);
    }
    return out;
  });

  readonly filterActive = computed(() => !!this.role() || !!this.query().trim());

  constructor() {
    effect(() => {
      const id = this.gremiumId();
      const former = this.former();
      untracked(() => this.load(id, former));
    });
  }

  load(id = this.gremiumId(), former = this.former()): void {
    this.sub?.unsubscribe();
    this.loading.set(true);
    this.error.set(false);
    this.sub = this.api.members(id, former).subscribe({
      next: (rows) => {
        this.members.set(rows);
        this.loading.set(false);
      },
      error: () => {
        this.members.set([]);
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  setFormer(value: string): void {
    this.role.set('');
    this.former.set(value === 'former');
  }

  /** "Als CSV exportieren": the rows that the list shows. */
  exportCsv(): void {
    const t = (k: Parameters<I18nService['translate']>[0]) => this.i18n.translate(k);
    const locale = this.i18n.locale();
    const rows = this.visible().map((r) => [
      r.name,
      r.member.email ?? '',
      localized(r.member.roleName, locale, r.member.roleKey),
      dayMonthYear(r.member.validFrom, this.i18n.formatLocale()),
      dayMonthYear(r.member.validUntil, this.i18n.formatLocale()),
    ]);
    const csv = toCsv([
      [t('gremien.members.colName'), t('gremien.members.colEmail'), t('gremien.members.colRole'), t('gremien.members.colFrom'), t('gremien.members.colUntil')],
      ...rows,
    ]);
    const suffix = this.former() ? '-ehemalige' : '';
    downloadBlob(new Blob([csv], { type: 'text/csv;charset=utf-8' }), `${fileSlug(this.gremiumName())}-mitglieder${suffix}.csv`);
  }

  /** "seit 01.10.2025 · bis 30.09.2026", or '' without a term. */
  private period(m: GremiumMember): string {
    const locale = this.i18n.formatLocale();
    const parts: string[] = [];
    if (m.validFrom) parts.push(this.i18n.translate('gremien.members.since', { date: dayMonthYear(m.validFrom, locale) }));
    if (m.validUntil) parts.push(this.i18n.translate('gremien.members.until', { date: dayMonthYear(m.validUntil, locale) }));
    return parts.join(' · ');
  }
}
