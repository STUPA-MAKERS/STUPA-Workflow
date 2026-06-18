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
import { mapDiff } from '@core/api/mappers';
import type { I18nMap, Uuid } from '@core/api/models';
import type { FormFieldDef } from '@core/api/models';
import {
  type AdminPrincipal,
  type ApplicationTypeCreateBody,
  type ApplicationTypeFull,
  type ApplicationTypeUpdateBody,
  type AuditActor,
  type AuditRevertResult,
  type ConfigRevision,
  type ConfigRevisionDiff,
  type ConfigRevisionDiffWire,
  type NotificationSettings,
  type AuditPage,
  type Branding,
  type FlowGraph,
  type FormDraft,
  type FormOverviewItem,
  type FormStatus,
  type Gremium,
  type GremiumCreateBody,
  type GremiumMembership,
  type DeadlinePolicy,
  type ErasureRequest,
  type ErasureStatus,
  type PrivacySettings,
  type GremiumRole,
  type GremiumUpdateBody,
  type GroupMapping,
  type GroupMappingBody,
  type MailPreview,
  type MailPreviewPayload,
  type MailTemplate,
  type MailTemplateUpsertBody,
  type Role,
  type RoleAssignment,
  type RoleAssignmentInput,
  type SiteConfig,
  type WebhookConfig,
} from './admin.models';
import {
  MOCK_APP_TYPES,
  MOCK_BRANDING,
  MOCK_FORM_DRAFTS,
  MOCK_FORMS,
  MOCK_GREMIEN,
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
  hasBudget?: boolean;
  retentionMonths?: number | null;
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
    appTypes: structuredCopy(MOCK_APP_TYPES),
    formDrafts: structuredCopy(MOCK_FORM_DRAFTS) as Record<string, FormDraft>,
    gremiumRoles: [] as GremiumRole[],
    deadlinePolicies: [] as DeadlinePolicy[],
    erasures: [] as ErasureRequest[],
    privacySettings: <PrivacySettings>{ defaultRetentionMonths: 24 },
    webhooks: structuredCopy(MOCK_WEBHOOKS),
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
   * (`/admin/gremien`, P `admin.gremien`) für »Sitzung anlegen«/Budget nutzbar,
   * wo der Akteur nur `meeting.manage`/`budget.*` hat.
   */
  listGremienOptions(): Observable<Gremium[]> {
    if (this.mock) return of(structuredCopy(this.store.gremien));
    return this.http.get<Gremium[]>(`${this.base}/gremien`);
  }

  /** POST /admin/gremien — Gremium anlegen (P `admin.gremien`), #105. */
  createGremium(body: GremiumCreateBody): Observable<Gremium> {
    if (this.mock) {
      const created: Gremium = { id: `g-${this.store.gremien.length + 1}`, allowVoteDelegation: false, ...body };
      this.store.gremien.push(created);
      return of(structuredCopy(created));
    }
    return this.http.post<Gremium>(`${this.base}/admin/gremien`, body);
  }

  /** PATCH /admin/gremien/{id} — Gremium bearbeiten (P `admin.gremien`), #105. */
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

  /** GET /admin/gremien/{id}/mail-recipients — Zusatz-Protokoll-Empfänger (#protocol-recipients). */
  getGremiumMailRecipients(id: Uuid): Observable<{ recipients: string[] }> {
    if (this.mock) return of({ recipients: [] });
    return this.http.get<{ recipients: string[] }>(
      `${this.base}/admin/gremien/${id}/mail-recipients`,
    );
  }

  /** PUT /admin/gremien/{id}/mail-recipients — Zusatz-Empfänger ersetzen (idempotent). */
  setGremiumMailRecipients(id: Uuid, recipients: string[]): Observable<{ recipients: string[] }> {
    if (this.mock) return of({ recipients });
    return this.http.put<{ recipients: string[] }>(
      `${this.base}/admin/gremien/${id}/mail-recipients`,
      { recipients },
    );
  }

  listRoles(): Observable<Role[]> {
    if (this.mock) return of(structuredCopy(this.store.roles));
    return this.http.get<Role[]>(`${this.base}/admin/roles`);
  }

  // --- OIDC-Gruppen → Rolle Mappings (#5-4) ---------------------------------
  listGroupMappings(): Observable<GroupMapping[]> {
    return this.http.get<GroupMapping[]>(`${this.base}/admin/group-mappings`);
  }
  createGroupMapping(body: GroupMappingBody): Observable<GroupMapping> {
    return this.http.post<GroupMapping>(`${this.base}/admin/group-mappings`, body);
  }
  updateGroupMapping(id: Uuid, body: Partial<GroupMappingBody>): Observable<GroupMapping> {
    return this.http.patch<GroupMapping>(`${this.base}/admin/group-mappings/${id}`, body);
  }
  deleteGroupMapping(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/admin/group-mappings/${id}`);
  }

  // --- Mail-Templates (#5-4) ------------------------------------------------
  listMailTemplates(): Observable<MailTemplate[]> {
    return this.http.get<MailTemplate[]>(`${this.base}/admin/mail-templates`);
  }
  /** Override per Key anlegen/aktualisieren (#12) — auch für Builtin-Defaults. */
  upsertMailTemplate(body: MailTemplateUpsertBody): Observable<MailTemplate> {
    return this.http.put<MailTemplate>(`${this.base}/admin/mail-templates`, body);
  }
  /** Override löschen → Builtin-Default wiederherstellen (#12). */
  resetMailTemplate(key: string): Observable<MailTemplate> {
    return this.http.delete<MailTemplate>(
      `${this.base}/admin/mail-templates/by-key/${encodeURIComponent(key)}`,
    );
  }
  /** Vorschau aus dem Editor-Entwurf (ohne ID, #12). */
  previewMailPayload(body: MailPreviewPayload): Observable<MailPreview> {
    return this.http.post<MailPreview>(`${this.base}/admin/mail-templates/preview`, body);
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
      return of(structuredCopy(this.store.roles[idx] ?? this.store.roles[0]));
    }
    return this.http.patch<Role>(`${this.base}/admin/roles/${roleId}`, { permissions });
  }

  /** Rolle umbenennen — Anzeigename (`label`), Key bleibt unverändert. */
  renameRole(roleId: Uuid, label: I18nMap): Observable<Role> {
    if (this.mock) {
      const idx = this.store.roles.findIndex((r) => r.id === roleId);
      if (idx >= 0) this.store.roles[idx] = { ...this.store.roles[idx], label: { ...label } };
      return of(structuredCopy(this.store.roles[idx] ?? this.store.roles[0]));
    }
    return this.http.patch<Role>(`${this.base}/admin/roles/${roleId}`, { label });
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

  // --- Antragstypen / Formulare (#13 — NC-Forms) ---------------------------
  /** Antragstypen als Editier-Sicht (id + i18n-Name + Gremium + Budget-Flag). */
  listApplicationTypesFull(): Observable<ApplicationTypeFull[]> {
    if (this.mock) return of(structuredCopy(this.store.appTypes));
    return this.http
      .get<ApplicationTypeOutWire[]>(`${this.base}/admin/application-types`)
      .pipe(
        map((list) =>
          list.map((t) => ({
            id: t.id,
            name: (t.nameI18n ?? {}) as I18nMap,
            gremiumId: t.gremiumId ?? null,
            hasBudget: t.hasBudget ?? false,
            retentionMonths: t.retentionMonths ?? null,
            activeFormVersionId: t.activeFormVersionId ?? null,
          })),
        ),
      );
  }

  /** Neuen Antragstyp/Formular anlegen — POST /admin/application-types (#13). */
  createApplicationType(body: ApplicationTypeCreateBody): Observable<ApplicationTypeFull> {
    if (this.mock) {
      const created: ApplicationTypeFull = {
        id: `f-${body.key || this.store.appTypes.length + 1}`,
        name: { ...body.name },
        gremiumId: body.gremiumId ?? null,
        hasBudget: body.hasBudget ?? false,
        activeFormVersionId: null,
      };
      this.store.appTypes = [...this.store.appTypes, created];
      return of(structuredCopy(created));
    }
    return this.http
      .post<ApplicationTypeOutWire>(`${this.base}/admin/application-types`, {
        key: body.key,
        nameI18n: body.name,
        gremiumId: body.gremiumId ?? null,
        hasBudget: body.hasBudget ?? false,
      })
      .pipe(
        map((t) => ({
          id: t.id,
          name: (t.nameI18n ?? {}) as I18nMap,
          gremiumId: t.gremiumId ?? null,
          hasBudget: t.hasBudget ?? false,
          retentionMonths: t.retentionMonths ?? null,
          activeFormVersionId: t.activeFormVersionId ?? null,
        })),
      );
  }

  /** Antragstyp-Stammdaten ändern (Titel/Gremium/Budget) — PATCH (#13). */
  updateApplicationType(id: Uuid, body: ApplicationTypeUpdateBody): Observable<void> {
    if (this.mock) {
      const row = this.store.appTypes.find((t) => t.id === id);
      if (row) {
        if (body.name) row.name = { ...body.name };
        if (body.gremiumId !== undefined) row.gremiumId = body.gremiumId;
        if (body.hasBudget !== undefined) row.hasBudget = body.hasBudget;
      }
      return of(void 0);
    }
    const payload: Record<string, unknown> = {};
    if (body.name) payload['nameI18n'] = body.name;
    if (body.gremiumId !== undefined) payload['gremiumId'] = body.gremiumId;
    if (body.hasBudget !== undefined) payload['hasBudget'] = body.hasBudget;
    return this.http
      .patch<unknown>(`${this.base}/admin/application-types/${id}`, payload)
      .pipe(map(() => void 0));
  }

  /** Antragsart löschen — eigene Permission ``admin.types_delete``; 409 bei
   *  bestehenden Anträgen dieser Art (#delete-types). */
  deleteApplicationType(id: Uuid): Observable<void> {
    if (this.mock) {
      this.store.appTypes = this.store.appTypes.filter((t) => t.id !== id);
      return of(void 0);
    }
    return this.http
      .delete<unknown>(`${this.base}/admin/application-types/${id}`)
      .pipe(map(() => void 0));
  }

  /** Aktuelle Form-Version eines Typs zum Bearbeiten laden (#13). */
  getFormDraft(typeId: Uuid): Observable<FormDraft> {
    if (this.mock) {
      const draft = this.store.formDrafts[typeId];
      return of(draft ? structuredCopy(draft) : { applicationTypeId: typeId, fields: [] });
    }
    return this.http.get<FormDraft>(
      `${this.base}/admin/application-types/${typeId}/form-versions/latest`,
    );
  }

  // --- Form-/Flow-Versionen ------------------------------------------------
  /** POST neue Form-Version (Definition serverseitig gegen JSON-Schema validiert). */
  createFormVersion(
    typeId: Uuid,
    fields: FormFieldDef[],
    description?: I18nMap | null,
  ): Observable<{ id: Uuid }> {
    if (this.mock) {
      const id = `formver-${fields.length}`;
      // Draft + Typ im Store nachführen, damit Reload den gespeicherten Stand zeigt.
      this.store.formDrafts[typeId] = {
        applicationTypeId: typeId,
        formVersionId: id,
        version: (this.store.formDrafts[typeId]?.version ?? 0) + 1,
        active: true,
        description: description ?? null,
        fields: structuredCopy(fields),
      };
      const t = this.store.appTypes.find((x) => x.id === typeId);
      if (t) t.activeFormVersionId = id;
      return of({ id });
    }
    return this.http.post<{ id: Uuid }>(
      `${this.base}/admin/application-types/${typeId}/form-versions`,
      { fields, description: description ?? null },
    );
  }

  /** Formular eines Typs aktivieren/deaktivieren (#forms) — gibt den aktualisierten Draft zurück. */
  setFormActive(typeId: Uuid, active: boolean): Observable<FormDraft> {
    if (this.mock) {
      const draft = this.store.formDrafts[typeId];
      if (draft) draft.active = active;
      const t = this.store.appTypes.find((x) => x.id === typeId);
      if (t) t.activeFormVersionId = active ? (draft?.formVersionId ?? null) : null;
      return of(draft ?? { applicationTypeId: typeId, active, fields: [] });
    }
    return this.http.patch<FormDraft>(
      `${this.base}/admin/application-types/${typeId}/form-active`,
      { active },
    );
  }

  /** Aktiven globalen Flow (#28) laden — `null`, wenn noch keiner existiert. */
  getGlobalFlow(): Observable<FlowGraph | null> {
    if (this.mock) return of(null);
    return this.http.get<FlowGraph | null>(`${this.base}/admin/flow-versions/global`);
  }

  /** Globalen Flow als neue Version anlegen (#28). */
  createGlobalFlowVersion(graph: FlowGraph): Observable<{ id: Uuid }> {
    if (this.mock) return of({ id: `gflow-${graph.states.length}` });
    return this.http.post<{ id: Uuid }>(`${this.base}/admin/flow-versions/global`, { graph });
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

  // --- Gremium-Rollen (#42/#62 — pro Gremium) ------------------------------
  listGremiumRoles(gremiumId: Uuid): Observable<GremiumRole[]> {
    if (this.mock) return of(structuredCopy(this.store.gremiumRoles.filter((r) => r.gremiumId === gremiumId)));
    return this.http.get<GremiumRole[]>(`${this.base}/admin/gremien/${gremiumId}/roles`);
  }

  createGremiumRole(
    gremiumId: Uuid,
    body: { key: string; name: I18nMap; permissions?: string[] },
  ): Observable<GremiumRole> {
    if (this.mock) {
      const row = { id: `gr-${this.store.gremiumRoles.length + 1}`, gremiumId, ...body };
      this.store.gremiumRoles = [...this.store.gremiumRoles, row];
      return of(structuredCopy(row));
    }
    return this.http.post<GremiumRole>(`${this.base}/admin/gremien/${gremiumId}/roles`, body);
  }

  updateGremiumRole(
    id: Uuid,
    body: { name?: I18nMap; permissions?: string[] },
  ): Observable<GremiumRole> {
    if (this.mock) {
      const row = this.store.gremiumRoles.find((r) => r.id === id);
      if (row) Object.assign(row, body);
      return of(structuredCopy(row ?? { id, gremiumId: '', key: '', name: body.name ?? {} }));
    }
    return this.http.patch<GremiumRole>(`${this.base}/admin/gremium-roles/${id}`, body);
  }

  /** Granulare Berechtigungen einer Gremium-Rolle setzen (#Sessions). */
  saveGremiumRolePermissions(id: Uuid, permissions: string[]): Observable<GremiumRole> {
    return this.updateGremiumRole(id, { permissions });
  }

  deleteGremiumRole(id: Uuid): Observable<void> {
    if (this.mock) {
      this.store.gremiumRoles = (this.store.gremiumRoles ?? []).filter((r) => r.id !== id);
      return of(void 0);
    }
    return this.http.delete<void>(`${this.base}/admin/gremium-roles/${id}`);
  }

  // --- Deadline-Policies (benannte Fristen, Registry) ----------------------
  listDeadlinePolicies(): Observable<DeadlinePolicy[]> {
    if (this.mock) return of(structuredCopy(this.store.deadlinePolicies));
    return this.http.get<DeadlinePolicy[]>(`${this.base}/admin/deadline-policies`);
  }

  createDeadlinePolicy(body: Omit<DeadlinePolicy, 'id'>): Observable<DeadlinePolicy> {
    if (this.mock) {
      const row = { id: `dp-${this.store.deadlinePolicies.length + 1}`, ...body };
      this.store.deadlinePolicies = [...this.store.deadlinePolicies, row];
      return of(structuredCopy(row));
    }
    return this.http.post<DeadlinePolicy>(`${this.base}/admin/deadline-policies`, body);
  }

  updateDeadlinePolicy(id: Uuid, body: Partial<Omit<DeadlinePolicy, 'id' | 'key'>>): Observable<DeadlinePolicy> {
    if (this.mock) {
      const row = this.store.deadlinePolicies.find((r) => r.id === id);
      if (row) Object.assign(row, body);
      return of(structuredCopy(row ?? ({ id, key: '', label: {}, kind: 'absolute' } as DeadlinePolicy)));
    }
    return this.http.patch<DeadlinePolicy>(`${this.base}/admin/deadline-policies/${id}`, body);
  }

  deleteDeadlinePolicy(id: Uuid): Observable<void> {
    if (this.mock) {
      this.store.deadlinePolicies = this.store.deadlinePolicies.filter((r) => r.id !== id);
      return of(void 0);
    }
    return this.http.delete<void>(`${this.base}/admin/deadline-policies/${id}`);
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
  /** Keyset-gepagtes Audit-Log. `before` = Cursor (id), Filter action/actor/Zeit. */
  listAuditLog(
    opts: {
      limit?: number;
      before?: number;
      action?: string;
      actor?: string;
      since?: string;
      until?: string;
    } = {},
  ): Observable<AuditPage> {
    const limit = opts.limit ?? 50;
    if (this.mock) return of({ items: [], nextCursor: null, hasMore: false });
    let params = new HttpParams().set('limit', String(limit));
    if (opts.before != null) params = params.set('before', String(opts.before));
    if (opts.action) params = params.set('action', opts.action);
    if (opts.actor) params = params.set('actor', opts.actor);
    if (opts.since) params = params.set('since', opts.since);
    if (opts.until) params = params.set('until', opts.until);
    return this.http.get<AuditPage>(`${this.base}/admin/audit`, { params });
  }

  /** Distinkte Akteure des Audit-Logs (für den Actor-Filter). */
  listAuditActors(): Observable<AuditActor[]> {
    if (this.mock) return of([]);
    return this.http.get<AuditActor[]>(`${this.base}/admin/audit/actors`);
  }

  /** Einen Config-Change aus dem Audit-Log zurücknehmen (P audit.revert).
   *  409 = neuerer Stand existiert / nicht revertierbar; 404 = Eintrag/Revision fehlt. */
  revertAuditEntry(entryId: number): Observable<AuditRevertResult> {
    return this.http.post<AuditRevertResult>(
      `${this.base}/admin/audit/${entryId}/revert`,
      {},
    );
  }

  // --- Config-Versionen (#config-versioning) -------------------------------
  /** Snapshots einer Config-Entität (neueste zuerst) — Versions-Sidebar. */
  listConfigRevisions(
    entityType: string,
    entityId: string,
  ): Observable<ConfigRevision[]> {
    if (this.mock) return of([]);
    const params = new HttpParams()
      .set('entityType', entityType)
      .set('entityId', entityId);
    return this.http.get<ConfigRevision[]>(`${this.base}/admin/config-revisions`, {
      params,
    });
  }

  /** Feld-Diff eines Snapshots gegen seinen Vorgänger (Wire → Array-Form). */
  getConfigRevisionDiff(id: Uuid): Observable<ConfigRevisionDiff> {
    if (this.mock) {
      return of({
        id,
        entityType: '',
        entityId: '',
        version: 0,
        prevVersion: null,
        diff: null,
      });
    }
    return this.http
      .get<ConfigRevisionDiffWire>(`${this.base}/admin/config-revisions/${id}/diff`)
      .pipe(map((w) => ({ ...w, diff: mapDiff(w.diff) })));
  }

  /** Einen früheren Snapshot als neue aktive Version zurückspielen (Sidebar-Restore). */
  restoreConfigRevision(id: Uuid): Observable<void> {
    return this.http.post<void>(
      `${this.base}/admin/config-revisions/${id}/restore`,
      {},
    );
  }

  // --- Benachrichtigungs-Config (#task-reminder, P(admin.notifications)) ----
  getNotificationSettings(): Observable<NotificationSettings> {
    if (this.mock) {
      return of({ taskReminderEnabled: true, taskReminderAfterDays: 5, taskReminderRepeatDays: 7 });
    }
    return this.http.get<NotificationSettings>(`${this.base}/admin/notification-settings`);
  }

  putNotificationSettings(
    settings: Partial<NotificationSettings>,
  ): Observable<NotificationSettings> {
    return this.http.put<NotificationSettings>(
      `${this.base}/admin/notification-settings`,
      settings,
    );
  }

  // --- DSGVO/Privacy (#PII-Re-Add, P privacy.manage) -----------------------
  listErasures(status?: ErasureStatus): Observable<ErasureRequest[]> {
    if (this.mock) {
      const rows = status
        ? this.store.erasures.filter((r) => r.status === status)
        : this.store.erasures;
      return of(structuredCopy(rows));
    }
    let params = new HttpParams();
    if (status) params = params.set('status', status);
    return this.http.get<ErasureRequest[]>(`${this.base}/admin/privacy/erasures`, {
      params,
    });
  }

  executeErasure(id: Uuid): Observable<ErasureRequest> {
    if (this.mock) {
      const row = this.store.erasures.find((r) => r.id === id);
      if (row) row.status = 'executed';
      return of(structuredCopy(row ?? ({ id } as ErasureRequest)));
    }
    return this.http.post<ErasureRequest>(
      `${this.base}/admin/privacy/erasures/${id}/execute`,
      {},
    );
  }

  rejectErasure(id: Uuid, reason?: string | null): Observable<ErasureRequest> {
    if (this.mock) {
      const row = this.store.erasures.find((r) => r.id === id);
      if (row) {
        row.status = 'rejected';
        row.reason = reason ?? null;
      }
      return of(structuredCopy(row ?? ({ id } as ErasureRequest)));
    }
    return this.http.post<ErasureRequest>(
      `${this.base}/admin/privacy/erasures/${id}/reject`,
      { reason: reason ?? null },
    );
  }

  erasePrincipal(id: Uuid): Observable<void> {
    if (this.mock) return of(void 0);
    return this.http.post<void>(`${this.base}/admin/privacy/principals/${id}/erase`, {});
  }

  getPrivacySettings(): Observable<PrivacySettings> {
    if (this.mock) return of(structuredCopy(this.store.privacySettings));
    return this.http.get<PrivacySettings>(`${this.base}/admin/privacy/settings`);
  }

  putPrivacySettings(settings: PrivacySettings): Observable<PrivacySettings> {
    if (this.mock) {
      this.store.privacySettings = structuredCopy(settings);
      return of(structuredCopy(this.store.privacySettings));
    }
    return this.http.put<PrivacySettings>(`${this.base}/admin/privacy/settings`, settings);
  }

  /** DSGVO-Auskunft (Art. 15) als XLSX-Blob (per E-Mail). */
  downloadAuskunft(email: string): Observable<Blob> {
    if (this.mock) return of(new Blob([], { type: 'application/octet-stream' }));
    const params = new HttpParams().set('email', email);
    return this.http.get(`${this.base}/admin/privacy/auskunft`, {
      params,
      responseType: 'blob',
    });
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
