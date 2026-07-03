import { Injectable, inject } from '@angular/core';
import { type Observable, map } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { resolveI18n } from '@shared/forms/i18n-text';
import type { SelectOption } from '@stupa-makers/ui-kit';
import { AdminApiService } from './admin-api.service';
import { MOCK_ROLES } from './admin.mock';
import {
  EVENT_NAMES,
  type EventName,
  GUARD_LEAF_OPERATORS,
  type RecipientKind,
} from './admin.models';

const RECIPIENT_KINDS: readonly RecipientKind[] = ['applicant', 'role', 'group'];

/**
 * Options provider for dropdowns. Bundles the sources for fields with restricted
 * options (gremium, role, event, recipient kind, guard) in one place, instead of
 * free text or scattered inline lists. Prefers admin-API/config data; where that is
 * empty (in mock mode) a clean fallback list kicks in. Labels follow the active locale.
 *
 * With mock off, the sources are wired for real: gremien via `/gremien`
 * (authenticated), application types via `/application-types`, roles via `/admin/roles`.
 */
@Injectable({ providedIn: 'root' })
export class AdminOptionsService {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);

  /**
   * Gremien as options (id → display name), from `/gremien` (authenticated, no admin
   * right). Usable in "create meeting" and budget, where the actor does not
   * necessarily have `admin.config`.
   */
  gremiumOptions(): Observable<SelectOption[]> {
    return this.api
      .listGremienOptions()
      .pipe(map((list) => list.map((g) => ({ value: g.id, label: g.name }))));
  }

  /**
   * Application types as options (id → name) for the form/flow builders, from the
   * public `/application-types`. Replaces the hardcoded `'mock-type'`: the builder
   * saves against a real type UUID.
   */
  applicationTypeOptions(): Observable<SelectOption[]> {
    return this.api
      .listApplicationTypes()
      .pipe(map((list) => list.map((t) => ({ value: t.id, label: t.name }))));
  }

  /** Roles as options (key → localized label); fallback list when empty. */
  roleOptions(): Observable<SelectOption[]> {
    const lang = this.i18n.locale();
    return this.api.listRoles().pipe(
      map((list) => (list.length ? list : MOCK_ROLES)),
      map((list) => list.map((r) => ({ value: r.key, label: resolveI18n(r.label, lang) }))),
    );
  }

  /** Event names (whitelist) as humanized options. */
  eventOptions(): SelectOption[] {
    return EVENT_NAMES.map((ev) => ({ value: ev, label: humanizeEvent(ev) }));
  }

  /** Recipient kinds (applicant/role/group) — labels from the i18n catalogue. */
  recipientKindOptions(): SelectOption[] {
    return RECIPIENT_KINDS.map((k) => ({
      value: k,
      label: this.i18n.translate(`admin.notif.rcpt.${k}` as TranslationKey),
    }));
  }

  /** Guard operators (whitelist) as options — value == key. */
  guardOperatorOptions(): SelectOption[] {
    return GUARD_LEAF_OPERATORS.map((op) => ({ value: op, label: op }));
  }
}

/** `status_changed` → `Status changed` (display only, no per-event i18n key). */
function humanizeEvent(ev: EventName): string {
  const spaced = ev.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
