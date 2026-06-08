/**
 * Admin-Config-API-Client (T-34) gegen sds/api.md §3 »admin«.
 *
 * **WICHTIG — Vorgänger-Status:** T-24 (admin-API) ist auf der Branch-Basis
 * (`origin/main` bc275a8) **nicht gemergt**; `app/modules/admin` liefert nur
 * Tabellen, keine Router. Dieser Client baut deshalb gegen den **Contract**
 * (api.md). Im Mock-Modus (`USE_MOCK_API`, Default true bis das Backend steht)
 * bedient ein In-Memory-Store die UIs; im Real-Modus gehen die exakten REST-
 * Calls raus. Beim Merge von T-24 nur `USE_MOCK_API` auf false stellen — die
 * Real-Pfade sind bereits verdrahtet.
 *
 * Branding/Site-Config (#21) ist **kein** SDS-Endpunkt; der Pfad
 * `/api/admin/site-config` ist eine T-34-Festlegung. TODO(T-24/#21): mit Backend
 * abstimmen.
 */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { type Observable, map, of } from 'rxjs';
import { API_BASE_URL, USE_MOCK_API } from '@core/api/api.config';
import type { I18nMap, Page, Uuid } from '@core/api/models';
import type { FormFieldDef } from '@core/api/models';
import {
  type AdminPrincipal,
  type AuditEntry,
  type Branding,
  type FlowGraph,
  type FormOverviewItem,
  type FormStatus,
  type Gremium,
  type GremiumCreateBody,
  type GremiumMembership,
  type GremiumRole,
  type GremiumUpdateBody,
  type NotificationRule,
  type Role,
  type RoleAssignment,
  type RoleAssignmentInput,
  type SiteConfig,
  type WebhookConfig,
} from './admin.models';
import {
  MOCK_BRANDING,
  MOCK_FORMS,
  MOCK_GREMIEN,
  MOCK_NOTIFICATION_RULES,
  MOCK_PERMISSIONS,
  MOCK_PRINCIPALS,
  MOCK_ROLES,
  MOCK_WEBHOOKS,
} from './admin.mock';

/** JSON-Schema-Export des Backends (`export_json_schemas`, config_schemas). */
export type ConfigSchemas = Record<string, Record<string, unknown>>;

/** Antragstyp als Auswahl-Quelle (id + Anzeigename), #69. */
export interface ApplicationTypeOption {
  id: Uuid;
  name: string;
}

/** Roh-Form von `GET /admin/application-types` (`ApplicationTypeOut`). */
interface ApplicationTypeOutWire {
  id: Uuid;
  nameI18n?: Record<string, string> | null;
  gremiumId?: Uuid | null;
  activeFormVersionId?: Uuid | null;
}

@Injectable({ providedIn: 'root' })
export class AdminApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);
  private readonly mock = inject(USE_MOCK_API);

  // In-Memory-Store (nur Mock-Modus). Pro Service-Instanz, reicht für UI/Tests.
  private readonly store = {
    gremien: structuredCopy(MOCK_GREMIEN),
    gremiumRoles: [] as GremiumRole[],
    webhooks: structuredCopy(MOCK_WEBHOOKS),
    rules: structuredCopy(MOCK_NOTIFICATION_RULES),
    roles: structuredCopy(MOCK_ROLES),
    principals: structuredCopy(MOCK_PRINCIPALS),
    site: <SiteConfig>{
      version: 1,
      active: structuredCopy(MOCK_BRANDING),
      draft: structuredCopy(MOCK_BRANDING),
      hasDraftChanges: false,
    },
  };

  // --- Schemas -------------------------------------------------------------
  configSchemas(): Observable<ConfigSchemas> {
    if (this.mock) return of(MOCK_CONFIG_SCHEMAS);
    return this.http.get<ConfigSchemas>(`${this.base}/admin/config-schemas`);
  }

  // --- Gremien / RBAC ------------------------------------------------------
  listGremien(): Observable<Gremium[]> {
    if (this.mock) return of(structuredCopy(this.store.gremien));
    return this.http.get<Gremium[]>(`${this.base}/admin/gremien`);
  }

  /**
   * Gremien-Stammdaten als Dropdown-Quelle (#68) — GET `/gremien` (kein
   * Admin-Recht; jeder eingeloggte Principal). Anders als {@link listGremien}
   * (`/admin/gremien`, P `admin.config`) für »Sitzung anlegen«/Budget nutzbar,
   * wo der Akteur nur `meeting.manage`/`budget.*` hat.
   */
  listGremienOptions(): Observable<Gremium[]> {
    if (this.mock) return of(structuredCopy(this.store.gremien));
    return this.http.get<Gremium[]>(`${this.base}/gremien`);
  }

  /** POST /admin/gremien — Gremium anlegen (P `admin.config`), #105. */
  createGremium(body: GremiumCreateBody): Observable<Gremium> {
    if (this.mock) {
      const created: Gremium = { id: `g-${this.store.gremien.length + 1}`, allowVoteDelegation: false, ...body };
      this.store.gremien.push(created);
      return of(structuredCopy(created));
    }
    return this.http.post<Gremium>(`${this.base}/admin/gremien`, body);
  }

  /** PATCH /admin/gremien/{id} — Gremium bearbeiten (P `admin.config`), #105. */
  updateGremium(id: Uuid, body: GremiumUpdateBody): Observable<Gremium> {
    if (this.mock) {
      const row = this.store.gremien.find((g) => g.id === id);
      if (row) Object.assign(row, body);
      return of(structuredCopy(row ?? this.store.gremien[0]));
    }
    return this.http.patch<Gremium>(`${this.base}/admin/gremien/${id}`, body);
  }

  deleteGremium(id: Uuid): Observable<void> {
    if (this.mock) {
      this.store.gremien = this.store.gremien.filter((g) => g.id !== id);
      return of(void 0);
    }
    return this.http.delete<void>(`${this.base}/admin/gremien/${id}`);
  }

  listRoles(): Observable<Role[]> {
    if (this.mock) return of(structuredCopy(this.store.roles));
    return this.http.get<Role[]>(`${this.base}/admin/roles`);
  }

  /**
   * Antragstypen (id + Name) als Auswahl-Quelle für die Form-/Flow-Builder (#69).
   * Nutzt das öffentliche `/application-types` (Page); ein `form.configure`-
   * Principal erhält dort auch inaktive Typen. Im Mock eine kleine Stub-Liste.
   */
  listApplicationTypes(): Observable<ApplicationTypeOption[]> {
    if (this.mock) return of(structuredCopy(MOCK_APP_TYPE_OPTIONS));
    return this.http
      .get<{ items: ApplicationTypeOption[] }>(`${this.base}/application-types`)
      .pipe(map((page) => page.items.map((t) => ({ id: t.id, name: t.name }))));
  }

  /** Überblick aktiver Formulare (#75): Name/Gremium/Status/Version. */
  listForms(): Observable<FormOverviewItem[]> {
    if (this.mock) return of(structuredCopy(MOCK_FORMS));
    // `/admin/application-types` liefert `ApplicationTypeOut` (nameI18n,
    // activeFormVersionId …), nicht die FE-View → mappen statt roh casten,
    // sonst zeigt die Tabelle leeren Namen + `status.undefined` (Image 11).
    return this.http
      .get<ApplicationTypeOutWire[]>(`${this.base}/admin/application-types`)
      .pipe(
        map((list) =>
          list.map((t) => ({
            id: t.id,
            name: t.nameI18n ?? {},
            gremiumId: t.gremiumId ?? null,
            status: (t.activeFormVersionId ? 'active' : 'draft') as FormStatus,
            version: 0,
          })),
        ),
      );
  }

  /** Rechte einer Rolle ändern (#72) — PATCH /admin/roles/{id} (`permissions`). */
  saveRolePermissions(roleId: Uuid, permissions: string[]): Observable<Role> {
    if (this.mock) {
      const idx = this.store.roles.findIndex((r) => r.id === roleId);
      if (idx >= 0) this.store.roles[idx] = { ...this.store.roles[idx], permissions: [...permissions] };
      return of(structuredCopy(this.store.roles[idx]));
    }
    return this.http.patch<Role>(`${this.base}/admin/roles/${roleId}`, { permissions });
  }

  /** Globale Rolle anlegen (#21) — POST /admin/roles (`RoleCreate`). */
  createRole(body: { key: string; label: I18nMap; permissions?: string[] }): Observable<Role> {
    if (this.mock) {
      const role: Role = {
        id: `role-${this.store.roles.length + 1}`,
        key: body.key,
        label: { ...body.label },
        permissions: [...(body.permissions ?? [])],
      };
      this.store.roles.push(role);
      return of(structuredCopy(role));
    }
    return this.http.post<Role>(`${this.base}/admin/roles`, body);
  }

  /** Benutzer aktivieren/deaktivieren (#30) — PATCH /admin/principals/{id}. */
  setPrincipalActive(principalId: Uuid, active: boolean): Observable<AdminPrincipal> {
    if (this.mock) {
      const p = this.store.principals.find((x) => x.id === principalId);
      if (p) p.active = active;
      return of(structuredCopy(p ?? this.store.principals[0]));
    }
    return this.http.patch<AdminPrincipal>(`${this.base}/admin/principals/${principalId}`, { active });
  }

  /** Rolle löschen (#38) — DELETE /admin/roles/{id} (admin/member serverseitig geschützt). */
  deleteRole(roleId: Uuid): Observable<void> {
    if (this.mock) {
      this.store.roles = this.store.roles.filter((r) => r.id !== roleId);
      return of(void 0);
    }
    return this.http.delete<void>(`${this.base}/admin/roles/${roleId}`);
  }

  /** Katalog wählbarer Permission-Keys (GET /admin/permissions). */
  listPermissions(): Observable<string[]> {
    if (this.mock) return of([...MOCK_PERMISSIONS]);
    return this.http.get<string[]>(`${this.base}/admin/permissions`);
  }

  // --- Benutzer & Rollen (#72) --------------------------------------------
  /** Benutzer (OIDC-Principals) auflisten/suchen — GET /admin/principals?q=. */
  listPrincipals(query?: string): Observable<AdminPrincipal[]> {
    if (this.mock) {
      const q = (query ?? '').trim().toLowerCase();
      const hit = (p: AdminPrincipal) =>
        !q ||
        p.sub.toLowerCase().includes(q) ||
        (p.email ?? '').toLowerCase().includes(q) ||
        (p.displayName ?? '').toLowerCase().includes(q);
      return of(structuredCopy(this.store.principals.filter(hit)));
    }
    const url = query ? `${this.base}/admin/principals?q=${encodeURIComponent(query)}` : `${this.base}/admin/principals`;
    return this.http.get<AdminPrincipal[]>(url);
  }

  /** Rolle zuweisen (#72) — POST /admin/role-assignments. */
  assignRole(input: RoleAssignmentInput): Observable<RoleAssignment> {
    if (this.mock) {
      const assignment: RoleAssignment = {
        id: `assign-${Math.abs(hashString(input.principalId + input.roleId + (input.validFrom ?? '')))}`,
        principalId: input.principalId,
        roleId: input.roleId,
        gremiumId: input.gremiumId ?? null,
        grantedBy: 'mock-admin',
        validFrom: input.validFrom ?? null,
        validUntil: input.validUntil ?? null,
        delegateVoting: input.delegateVoting ?? false,
      };
      const p = this.store.principals.find((x) => x.id === input.principalId);
      if (p) p.assignments = [...p.assignments, assignment];
      return of(structuredCopy(assignment));
    }
    return this.http.post<RoleAssignment>(`${this.base}/admin/role-assignments`, input);
  }

  /** Rolle entziehen (#72) — DELETE /admin/role-assignments/{id}. */
  revokeRole(assignmentId: Uuid): Observable<void> {
    if (this.mock) {
      for (const p of this.store.principals) {
        p.assignments = p.assignments.filter((a) => a.id !== assignmentId);
      }
      return of(void 0);
    }
    return this.http.delete<void>(`${this.base}/admin/role-assignments/${assignmentId}`);
  }

  // --- Form-/Flow-Versionen ------------------------------------------------
  /** POST neue Form-Version (Definition serverseitig gegen JSON-Schema validiert). */
  createFormVersion(typeId: Uuid, fields: FormFieldDef[]): Observable<{ id: Uuid }> {
    if (this.mock) return of({ id: `formver-${fields.length}` });
    return this.http.post<{ id: Uuid }>(
      `${this.base}/admin/application-types/${typeId}/form-versions`,
      { fields },
    );
  }

  /** POST neue Flow-Version (Graph serverseitig via `validate_flow_graph` geprüft). */
  createFlowVersion(typeId: Uuid, graph: FlowGraph): Observable<{ id: Uuid }> {
    if (this.mock) return of({ id: `flowver-${graph.states.length}` });
    return this.http.post<{ id: Uuid }>(
      `${this.base}/admin/application-types/${typeId}/flow-versions`,
      { graph },
    );
  }

  // --- Webhooks ------------------------------------------------------------
  listWebhooks(): Observable<WebhookConfig[]> {
    if (this.mock) return of(structuredCopy(this.store.webhooks));
    return this.http.get<WebhookConfig[]>(`${this.base}/admin/webhooks`);
  }

  saveWebhook(hook: WebhookConfig): Observable<WebhookConfig> {
    if (this.mock) return of(this.upsert(this.store.webhooks, hook, 'wh'));
    return hook.id
      ? this.http.patch<WebhookConfig>(`${this.base}/admin/webhooks/${hook.id}`, hook)
      : this.http.post<WebhookConfig>(`${this.base}/admin/webhooks`, hook);
  }

  // --- Gremium-Rollen (#42) ------------------------------------------------
  listGremiumRoles(): Observable<GremiumRole[]> {
    if (this.mock) return of(structuredCopy(this.store.gremiumRoles ?? []));
    return this.http.get<GremiumRole[]>(`${this.base}/admin/gremium-roles`);
  }

  createGremiumRole(body: { key: string; name: I18nMap }): Observable<GremiumRole> {
    if (this.mock) {
      const row = { id: `gr-${(this.store.gremiumRoles ?? []).length + 1}`, ...body };
      this.store.gremiumRoles = [...(this.store.gremiumRoles ?? []), row];
      return of(structuredCopy(row));
    }
    return this.http.post<GremiumRole>(`${this.base}/admin/gremium-roles`, body);
  }

  updateGremiumRole(id: Uuid, body: { name: I18nMap }): Observable<GremiumRole> {
    if (this.mock) {
      const row = (this.store.gremiumRoles ?? []).find((r) => r.id === id);
      if (row) Object.assign(row, body);
      return of(structuredCopy(row ?? { id, key: '', name: body.name }));
    }
    return this.http.patch<GremiumRole>(`${this.base}/admin/gremium-roles/${id}`, body);
  }

  deleteGremiumRole(id: Uuid): Observable<void> {
    if (this.mock) {
      this.store.gremiumRoles = (this.store.gremiumRoles ?? []).filter((r) => r.id !== id);
      return of(void 0);
    }
    return this.http.delete<void>(`${this.base}/admin/gremium-roles/${id}`);
  }

  listGremiumMemberships(gremiumId: Uuid): Observable<GremiumMembership[]> {
    if (this.mock) return of([]);
    return this.http.get<GremiumMembership[]>(`${this.base}/admin/gremien/${gremiumId}/memberships`);
  }

  createGremiumMembership(
    gremiumId: Uuid,
    body: { principalId: Uuid; gremiumRoleId: Uuid; validFrom: string | null; validUntil: string | null },
  ): Observable<GremiumMembership> {
    return this.http.post<GremiumMembership>(`${this.base}/admin/gremien/${gremiumId}/memberships`, body);
  }

  deleteGremiumMembership(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/admin/gremium-memberships/${id}`);
  }

  // --- Audit-Log (#45, P(audit.read)) --------------------------------------
  listAuditLog(
    opts: { limit?: number; offset?: number; action?: string; actor?: string } = {},
  ): Observable<Page<AuditEntry>> {
    const limit = opts.limit ?? 50;
    const offset = opts.offset ?? 0;
    if (this.mock) return of({ items: [], total: 0, limit, offset });
    let params = new HttpParams().set('limit', String(limit)).set('offset', String(offset));
    if (opts.action) params = params.set('action', opts.action);
    if (opts.actor) params = params.set('actor', opts.actor);
    return this.http.get<Page<AuditEntry>>(`${this.base}/admin/audit`, { params });
  }

  // --- Notification-Regeln -------------------------------------------------
  listNotificationRules(): Observable<NotificationRule[]> {
    if (this.mock) return of(structuredCopy(this.store.rules));
    return this.http.get<NotificationRule[]>(`${this.base}/admin/notification-rules`);
  }

  saveNotificationRule(rule: NotificationRule): Observable<NotificationRule> {
    if (this.mock) return of(this.upsert(this.store.rules, rule, 'nr'));
    return rule.id
      ? this.http.patch<NotificationRule>(`${this.base}/admin/notification-rules/${rule.id}`, rule)
      : this.http.post<NotificationRule>(`${this.base}/admin/notification-rules`, rule);
  }

  // --- Branding / Site-Config (#21 — Mock-Contract) ------------------------
  getSiteConfig(): Observable<SiteConfig> {
    if (this.mock) return of(structuredCopy(this.store.site));
    return this.http.get<SiteConfig>(`${this.base}/admin/site-config`);
  }

  /** Entwurf speichern (noch nicht aktiv) — PUT /admin/site-config/draft. */
  saveBrandingDraft(draft: Branding): Observable<SiteConfig> {
    if (this.mock) {
      this.store.site.draft = structuredCopy(draft);
      this.store.site.hasDraftChanges = true;
      return of(structuredCopy(this.store.site));
    }
    return this.http.put<SiteConfig>(`${this.base}/admin/site-config/draft`, draft);
  }

  /** Entwurf aktivieren → neue Version — POST /admin/site-config/activate. */
  activateBranding(): Observable<SiteConfig> {
    if (this.mock) {
      this.store.site.active = structuredCopy(this.store.site.draft);
      this.store.site.version += 1;
      this.store.site.hasDraftChanges = false;
      return of(structuredCopy(this.store.site));
    }
    return this.http.post<SiteConfig>(`${this.base}/admin/site-config/activate`, {});
  }

  // --- intern --------------------------------------------------------------
  private upsert<T extends { id: Uuid }>(list: T[], item: T, prefix: string): T {
    if (item.id) {
      const idx = list.findIndex((x) => x.id === item.id);
      if (idx >= 0) list[idx] = structuredCopy(item);
      return structuredCopy(item);
    }
    const created = { ...structuredCopy(item), id: `${prefix}-${list.length + 1}` };
    list.push(created);
    return structuredCopy(created);
  }
}

/** Deep-Copy ohne `structuredClone`-Verfügbarkeitsannahme (jsdom-sicher). */
function structuredCopy<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/** Stabiler String-Hash (deterministische Mock-IDs, kein `Math.random`/`Date`). */
function hashString(value: string): number {
  let h = 0;
  for (let i = 0; i < value.length; i++) h = (Math.imul(31, h) + value.charCodeAt(i)) | 0;
  return h;
}

/** Antragstyp-Stubs für den Mock-Modus (#69) — echte Typen kommen vom Backend. */
const MOCK_APP_TYPE_OPTIONS: ApplicationTypeOption[] = [
  { id: '11111111-1111-1111-1111-111111111111', name: 'Finanzantrag' },
  { id: '22222222-2222-2222-2222-222222222222', name: 'Sonstiger Antrag' },
];

/** Minimaler Schema-Stub für den Mock-Modus (echte Schemas kommen vom Backend). */
const MOCK_CONFIG_SCHEMAS: ConfigSchemas = {
  FormFieldDef: { title: 'FormFieldDef', type: 'object' },
  FlowGraph: { title: 'FlowGraph', type: 'object' },
};
