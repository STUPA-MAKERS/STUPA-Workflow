import { Injectable, inject } from '@angular/core';
import { type Observable, map } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { resolveI18n } from '@shared/forms/i18n-text';
import type { SelectOption } from '@shared/ui';
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
 * Options-Provider für Dropdowns (#77). Bündelt die Quellen für Felder mit
 * eingeschränkten Optionen (Gremium, Rolle, Ereignis, Empfänger-Typ, Guard) an
 * **einer** Stelle, statt Freitext oder verstreute Inline-Listen. Bevorzugt
 * Admin-API/Config-Daten; wo die (im Mock) leer sind, greift eine saubere
 * Fallback-Liste. Labels folgen der aktiven Locale.
 *
 * TODO(T-24-Verdrahtung): `/admin/gremien` + `/admin/roles` liefern real; der
 * Provider übernimmt sie automatisch, sobald `USE_MOCK_API=false`.
 */
@Injectable({ providedIn: 'root' })
export class AdminOptionsService {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);

  /** Gremien als Optionen (id → Anzeigename), aus `/admin/gremien`. */
  gremiumOptions(): Observable<SelectOption[]> {
    return this.api
      .listGremien()
      .pipe(map((list) => list.map((g) => ({ value: g.id, label: g.name }))));
  }

  /** Rollen als Optionen (key → lokalisiertes Label); Fallback-Liste wenn leer. */
  roleOptions(): Observable<SelectOption[]> {
    const lang = this.i18n.locale();
    return this.api.listRoles().pipe(
      map((list) => (list.length ? list : MOCK_ROLES)),
      map((list) => list.map((r) => ({ value: r.key, label: resolveI18n(r.label, lang) }))),
    );
  }

  /** Ereignis-Namen (Whitelist) als humanisierte Optionen. */
  eventOptions(): SelectOption[] {
    return EVENT_NAMES.map((ev) => ({ value: ev, label: humanizeEvent(ev) }));
  }

  /** Empfänger-Typen (applicant/role/group) — Labels aus dem i18n-Katalog. */
  recipientKindOptions(): SelectOption[] {
    return RECIPIENT_KINDS.map((k) => ({
      value: k,
      label: this.i18n.translate(`admin.notif.rcpt.${k}` as TranslationKey),
    }));
  }

  /** Guard-Operatoren (Whitelist) als Optionen — Wert == Schlüssel. */
  guardOperatorOptions(): SelectOption[] {
    return GUARD_LEAF_OPERATORS.map((op) => ({ value: op, label: op }));
  }
}

/** `status_changed` → `Status changed` (Anzeige, kein i18n-Key je Ereignis). */
function humanizeEvent(ev: EventName): string {
  const spaced = ev.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
