/**
 * Admin config API client (against the admin section of the HTTP API).
 *
 * In mock mode (`USE_MOCK_API`) an in-memory store serves the UIs. In real mode the
 * exact REST calls go out. Branding/site-config uses the local `/api/admin/site-config`
 * path, which is not part of the API spec.
 */
import { HttpClient, HttpParams } from '@angular/common/http';
import { skipLoading } from '@core/loading/loading.interceptor';
import { Injectable, inject } from '@angular/core';
import { type Observable, map, of } from 'rxjs';
import { API_BASE_URL, USE_MOCK_API } from '@core/api/api.config';
import { mapDiff } from '@core/api/mappers';
import type { I18nMap, Page, Uuid } from '@core/api/models';
import type { FormFieldDef } from '@core/api/models';
import {
  BACKUP_RESTORE_CONFIRMATION,
  type AdminPrincipal,
  type Backup,
  type BackupExport,
  type BackupList,
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
  type CdLogoSlot,
  type CdVariant,
  type CdVariantCreateBody,
  type CdVariantLogo,
  type CdVariantOption,
  type CdVariantUpdateBody,
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
  type OAuthGrantAdmin,
  type OAuthGrantQuery,
  type Role,
  type RoleAssignment,
  type RoleAssignmentPatch,
  type RoleAssignmentInput,
  type SiteConfig,
  type WebhookConfig,
  type WebhookDeliveryStatus,
} from './admin.models';
import {
  MOCK_APP_TYPES,
  MOCK_BACKUPS,
  MOCK_BRANDING,
  MOCK_FORM_DRAFTS,
  MOCK_FORMS,
  MOCK_GREMIEN,
  MOCK_PERMISSIONS,
  MOCK_PRINCIPALS,
  MOCK_ROLES,
  MOCK_WEBHOOKS,
} from './admin.mock';

/** Backend JSON-schema export (`export_json_schemas`). */
export type ConfigSchemas = Record<string, Record<string, unknown>>;

/** Application type as a selection source (id + display name). */
export interface ApplicationTypeOption {
  id: Uuid;
  name: string;
}

/** Raw shape of `GET /admin/application-types` (`ApplicationTypeOut`). */
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

  // In-memory store for mock mode only. One store per service instance is enough for
  // the UI and the tests.
  private readonly store = {
    gremien: structuredCopy(MOCK_GREMIEN),
    appTypes: structuredCopy(MOCK_APP_TYPES),
    formDrafts: structuredCopy(MOCK_FORM_DRAFTS) as Record<string, FormDraft>,
    gremiumRoles: [] as GremiumRole[],
    deadlinePolicies: [] as DeadlinePolicy[],
    erasures: [] as ErasureRequest[],
    backups: [...MOCK_BACKUPS] as Backup[],
    privacySettings: <PrivacySettings>{ defaultRetentionMonths: 24 },
    webhooks: structuredCopy(MOCK_WEBHOOKS),
    roles: structuredCopy(MOCK_ROLES),
    principals: structuredCopy(MOCK_PRINCIPALS),
    oauthGrants: structuredCopy(MOCK_OAUTH_GRANTS),
    site: <SiteConfig>{
      version: 1,
      active: structuredCopy(MOCK_BRANDING),
      draft: structuredCopy(MOCK_BRANDING),
      hasDraftChanges: false,
    },
  };

  configSchemas(): Observable<ConfigSchemas> {
    if (this.mock) return of(MOCK_CONFIG_SCHEMAS);
    return this.http.get<ConfigSchemas>(`${this.base}/admin/config-schemas`);
  }

  /** `quiet` = the gremien page shows its own loading indicator (no overlay). */
  listGremien(opts: { quiet?: boolean } = {}): Observable<Gremium[]> {
    if (this.mock) return of(structuredCopy(this.store.gremien));
    return this.http.get<Gremium[]>(`${this.base}/admin/gremien`, {
      context: opts.quiet ? skipLoading() : undefined,
    });
  }

  /**
   * Gremien master data as a dropdown source — GET `/gremien`. Any logged-in principal
   * can call it. No admin right is necessary. Unlike {@link listGremien}
   * (`/admin/gremien`, P `admin.gremien`), it also works for "create meeting" and for
   * budget, where the actor only holds `meeting.manage` or `budget.*`.
   */
  listGremienOptions(): Observable<Gremium[]> {
    if (this.mock) return of(structuredCopy(this.store.gremien));
    return this.http.get<Gremium[]>(`${this.base}/gremien`);
  }

  /** POST /admin/gremien — create a gremium (P `admin.gremien`). */
  createGremium(body: GremiumCreateBody): Observable<Gremium> {
    if (this.mock) {
      const created: Gremium = { id: `g-${this.store.gremien.length + 1}`, allowVoteDelegation: false, ...body };
      this.store.gremien.push(created);
      return of(structuredCopy(created));
    }
    return this.http.post<Gremium>(`${this.base}/admin/gremien`, body);
  }

  /** PATCH /admin/gremien/{id} — edit a gremium (P `admin.gremien`). */
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

  /** GET /admin/gremien/{id}/mail-recipients — extra protocol recipients. */
  getGremiumMailRecipients(id: Uuid): Observable<{ recipients: string[] }> {
    if (this.mock) return of({ recipients: [] });
    return this.http.get<{ recipients: string[] }>(
      `${this.base}/admin/gremien/${id}/mail-recipients`,
    );
  }

  /** PUT /admin/gremien/{id}/mail-recipients — replace extra recipients (idempotent). */
  setGremiumMailRecipients(id: Uuid, recipients: string[]): Observable<{ recipients: string[] }> {
    if (this.mock) return of({ recipients });
    return this.http.put<{ recipients: string[] }>(
      `${this.base}/admin/gremien/${id}/mail-recipients`,
      { recipients },
    );
  }

  // Corporate-design variants. Every `/admin/cd-variants` route needs
  // P `admin.cd_variants`. The page shows its own loading indicator, so the
  // list GET opts out of the global overlay.

  /** GET /admin/cd-variants — the variants with their title and footer logos. */
  listCdVariants(): Observable<CdVariant[]> {
    return this.http.get<CdVariant[]>(`${this.base}/admin/cd-variants`, {
      context: skipLoading(),
    });
  }

  /** POST /admin/cd-variants — 409 when the key already exists. */
  createCdVariant(body: CdVariantCreateBody): Observable<CdVariant> {
    return this.http.post<CdVariant>(`${this.base}/admin/cd-variants`, body);
  }

  /** PATCH /admin/cd-variants/{id} — name and base variant only. The key is immutable. */
  updateCdVariant(id: Uuid, body: CdVariantUpdateBody): Observable<CdVariant> {
    return this.http.patch<CdVariant>(`${this.base}/admin/cd-variants/${id}`, body);
  }

  /** DELETE /admin/cd-variants/{id} — 409 while a gremium still references it. */
  deleteCdVariant(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/admin/cd-variants/${id}`);
  }

  /** POST /admin/cd-variants/{id}/logos — multipart upload into a slot. */
  uploadCdVariantLogo(id: Uuid, slot: CdLogoSlot, file: File): Observable<CdVariantLogo> {
    const form = new FormData();
    form.append('slot', slot);
    form.append('file', file);
    return this.http.post<CdVariantLogo>(`${this.base}/admin/cd-variants/${id}/logos`, form);
  }

  /** POST /admin/cd-variants/{id}/logos/vendored — append a logo that pytex ships. */
  addCdVariantVendoredLogo(
    id: Uuid,
    slot: CdLogoSlot,
    vendoredName: string,
  ): Observable<CdVariantLogo> {
    return this.http.post<CdVariantLogo>(`${this.base}/admin/cd-variants/${id}/logos/vendored`, {
      slot,
      vendoredName,
    });
  }

  /** PUT /admin/cd-variants/{id}/logos/order — full new order of ONE slot. */
  reorderCdVariantLogos(
    id: Uuid,
    slot: CdLogoSlot,
    logoIds: Uuid[],
  ): Observable<CdVariantLogo[]> {
    return this.http.put<CdVariantLogo[]>(`${this.base}/admin/cd-variants/${id}/logos/order`, {
      slot,
      logoIds,
    });
  }

  /** DELETE /admin/cd-variant-logos/{id} — an uploaded object goes with the entry. */
  deleteCdVariantLogo(logoId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/admin/cd-variant-logos/${logoId}`);
  }

  /** Download URL of an uploaded logo. The server always answers `attachment`. */
  cdVariantLogoFileUrl(logoId: Uuid): string {
    return `${this.base}/admin/cd-variant-logos/${logoId}/file`;
  }

  /**
   * GET /cd-variants — slim list (id, key, name) as the source of the gremium
   * dropdown. `admin.gremien` is enough for it, `admin.cd_variants` is not needed.
   */
  listCdVariantOptions(): Observable<CdVariantOption[]> {
    if (this.mock) return of(structuredCopy(MOCK_CD_VARIANT_OPTIONS));
    return this.http.get<CdVariantOption[]>(`${this.base}/cd-variants`, {
      context: skipLoading(),
    });
  }

  listRoles(): Observable<Role[]> {
    if (this.mock) return of(structuredCopy(this.store.roles));
    return this.http.get<Role[]>(`${this.base}/admin/roles`);
  }

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

  listMailTemplates(): Observable<MailTemplate[]> {
    return this.http.get<MailTemplate[]>(`${this.base}/admin/mail-templates`);
  }
  /** Create/update an override by key — also for builtin defaults. */
  upsertMailTemplate(body: MailTemplateUpsertBody): Observable<MailTemplate> {
    return this.http.put<MailTemplate>(`${this.base}/admin/mail-templates`, body);
  }
  /** Delete an override → restore the builtin default. */
  resetMailTemplate(key: string): Observable<MailTemplate> {
    return this.http.delete<MailTemplate>(
      `${this.base}/admin/mail-templates/by-key/${encodeURIComponent(key)}`,
    );
  }
  /** Preview from the editor draft (no id). */
  previewMailPayload(body: MailPreviewPayload): Observable<MailPreview> {
    return this.http.post<MailPreview>(`${this.base}/admin/mail-templates/preview`, body);
  }

  /**
   * Application types (id + name) as a selection source for the form/flow builders.
   * It uses the public `/application-types` page. A `form.configure` principal also
   * gets the inactive types there. Mock mode returns a small stub list.
   */
  listApplicationTypes(): Observable<ApplicationTypeOption[]> {
    if (this.mock) return of(structuredCopy(MOCK_APP_TYPE_OPTIONS));
    return this.http
      .get<{ items: ApplicationTypeOption[] }>(`${this.base}/application-types`)
      .pipe(map((page) => page.items.map((t) => ({ id: t.id, name: t.name }))));
  }

  /** Overview of active forms: name/gremium/status/version. */
  listForms(): Observable<FormOverviewItem[]> {
    if (this.mock) return of(structuredCopy(MOCK_FORMS));
    // `/admin/application-types` returns `ApplicationTypeOut` (nameI18n,
    // activeFormVersionId …), not the FE view. Map the rows instead of a raw cast.
    // After a raw cast the table shows an empty name and `status.undefined`.
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

  /** Change a role's permissions — PATCH /admin/roles/{id} (`permissions`). */
  saveRolePermissions(roleId: Uuid, permissions: string[]): Observable<Role> {
    if (this.mock) {
      const idx = this.store.roles.findIndex((r) => r.id === roleId);
      if (idx >= 0) this.store.roles[idx] = { ...this.store.roles[idx], permissions: [...permissions] };
      return of(structuredCopy(this.store.roles[idx] ?? this.store.roles[0]));
    }
    return this.http.patch<Role>(`${this.base}/admin/roles/${roleId}`, { permissions });
  }

  /** Rename a role — change the display name (`label`). The key stays unchanged. */
  renameRole(roleId: Uuid, label: I18nMap): Observable<Role> {
    if (this.mock) {
      const idx = this.store.roles.findIndex((r) => r.id === roleId);
      if (idx >= 0) this.store.roles[idx] = { ...this.store.roles[idx], label: { ...label } };
      return of(structuredCopy(this.store.roles[idx] ?? this.store.roles[0]));
    }
    return this.http.patch<Role>(`${this.base}/admin/roles/${roleId}`, { label });
  }

  /** Create a global role — POST /admin/roles (`RoleCreate`). */
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

  /** Activate/deactivate a user — PATCH /admin/principals/{id}. */
  setPrincipalActive(principalId: Uuid, active: boolean): Observable<AdminPrincipal> {
    if (this.mock) {
      const p = this.store.principals.find((x) => x.id === principalId);
      if (p) p.active = active;
      return of(structuredCopy(p ?? this.store.principals[0]));
    }
    return this.http.patch<AdminPrincipal>(`${this.base}/admin/principals/${principalId}`, { active });
  }

  /** Delete a role — DELETE /admin/roles/{id} (admin/member protected server-side). */
  deleteRole(roleId: Uuid): Observable<void> {
    if (this.mock) {
      this.store.roles = this.store.roles.filter((r) => r.id !== roleId);
      return of(void 0);
    }
    return this.http.delete<void>(`${this.base}/admin/roles/${roleId}`);
  }

  /** Catalog of selectable permission keys (GET /admin/permissions). */
  listPermissions(): Observable<string[]> {
    if (this.mock) return of([...MOCK_PERMISSIONS]);
    return this.http.get<string[]>(`${this.base}/admin/permissions`);
  }

  /** List/search users (OIDC principals) — GET /admin/principals?q=. */
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

  /** Assign a role — POST /admin/role-assignments. */
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

  /**
   * Change an existing assignment — PATCH /admin/role-assignments/{id}.
   *
   * The route touches only the fields the body carries. It cannot clear a
   * validity window, and it never moves the assignment to another user.
   */
  updateRoleAssignment(assignmentId: Uuid, patch: RoleAssignmentPatch): Observable<RoleAssignment> {
    if (this.mock) {
      for (const p of this.store.principals) {
        const found = p.assignments.find((a) => a.id === assignmentId);
        if (!found) continue;
        const merged: RoleAssignment = { ...found, ...patch };
        p.assignments = p.assignments.map((a) => (a.id === assignmentId ? merged : a));
        return of(structuredCopy(merged));
      }
      return of(structuredCopy({ id: assignmentId, ...patch } as unknown as RoleAssignment));
    }
    return this.http.patch<RoleAssignment>(
      `${this.base}/admin/role-assignments/${assignmentId}`,
      patch,
    );
  }

  /** Revoke a role — DELETE /admin/role-assignments/{id}. */
  revokeRole(assignmentId: Uuid): Observable<void> {
    if (this.mock) {
      for (const p of this.store.principals) {
        p.assignments = p.assignments.filter((a) => a.id !== assignmentId);
      }
      return of(void 0);
    }
    return this.http.delete<void>(`${this.base}/admin/role-assignments/${assignmentId}`);
  }

  // OAuth grants of ANY principal. Both routes need P(`admin.users`). The
  // self-service twins under `/oauth/grants` reach the caller's own grants only, so a
  // leaked agent token of somebody else can be killed here and nowhere else.

  /**
   * GET /admin/oauth-grants — live (not revoked) grants, newest first.
   *
   * `principalId` narrows the list to one owner. The list drives its own status line,
   * so it opts out of the global loading overlay.
   */
  listOAuthGrants(query: OAuthGrantQuery = {}): Observable<Page<OAuthGrantAdmin>> {
    const limit = query.limit ?? 50;
    const offset = query.offset ?? 0;
    if (this.mock) {
      const all = this.store.oauthGrants.filter(
        (g) => !query.principalId || g.principalId === query.principalId,
      );
      return of({
        items: structuredCopy(all.slice(offset, offset + limit)),
        total: all.length,
        limit,
        offset,
      });
    }
    let params = new HttpParams().set('limit', String(limit)).set('offset', String(offset));
    if (query.principalId) params = params.set('principalId', query.principalId);
    return this.http.get<Page<OAuthGrantAdmin>>(`${this.base}/admin/oauth-grants`, {
      params,
      context: skipLoading(),
    });
  }

  /** DELETE /admin/oauth-grants/{id} — 204. A 404 means the grant is gone already. */
  revokeOAuthGrant(grantId: Uuid): Observable<void> {
    if (this.mock) {
      this.store.oauthGrants = this.store.oauthGrants.filter((g) => g.id !== grantId);
      return of(void 0);
    }
    return this.http.delete<void>(`${this.base}/admin/oauth-grants/${grantId}`);
  }

  /** Application types as an edit view (id + i18n name + gremium + budget flag). */
  listApplicationTypesFull(): Observable<ApplicationTypeFull[]> {
    if (this.mock) return of(structuredCopy(this.store.appTypes));
    return this.http
      .get<ApplicationTypeOutWire[]>(`${this.base}/admin/application-types`, {
        context: skipLoading(),
      })
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

  /** Create a new application type/form — POST /admin/application-types. */
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

  /** Edit application-type master data (title/gremium/budget) — PATCH. */
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

  /** Delete an application type. It needs the dedicated permission `admin.types_delete`.
   *  The server answers 409 if applications of this type exist. */
  deleteApplicationType(id: Uuid): Observable<void> {
    if (this.mock) {
      this.store.appTypes = this.store.appTypes.filter((t) => t.id !== id);
      return of(void 0);
    }
    return this.http
      .delete<unknown>(`${this.base}/admin/application-types/${id}`)
      .pipe(map(() => void 0));
  }

  /** Load a type's current form version for editing. */
  getFormDraft(typeId: Uuid): Observable<FormDraft> {
    if (this.mock) {
      const draft = this.store.formDrafts[typeId];
      return of(draft ? structuredCopy(draft) : { applicationTypeId: typeId, fields: [] });
    }
    return this.http.get<FormDraft>(
      `${this.base}/admin/application-types/${typeId}/form-versions/latest`,
      { context: skipLoading() },
    );
  }

  /** POST a new form version. The server validates the definition against a JSON schema. */
  createFormVersion(
    typeId: Uuid,
    fields: FormFieldDef[],
    description?: I18nMap | null,
  ): Observable<{ id: Uuid }> {
    if (this.mock) {
      const id = `formver-${fields.length}`;
      // Update draft + type in the store so a reload shows the saved state.
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

  /** Activate/deactivate a type's form — returns the updated draft. */
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

  /** Load the active global flow — `null` if none exists yet. */
  getGlobalFlow(): Observable<FlowGraph | null> {
    if (this.mock) return of(null);
    return this.http.get<FlowGraph | null>(`${this.base}/admin/flow-versions/global`);
  }

  /** Create the global flow as a new version. */
  createGlobalFlowVersion(graph: FlowGraph): Observable<{ id: Uuid }> {
    if (this.mock) return of({ id: `gflow-${graph.states.length}` });
    return this.http.post<{ id: Uuid }>(`${this.base}/admin/flow-versions/global`, { graph });
  }

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

  /** Delete a webhook and its delivery history. Needs P(`webhook.manage`). */
  deleteWebhook(id: Uuid): Observable<void> {
    if (this.mock) {
      this.store.webhooks = this.store.webhooks.filter((h) => h.id !== id);
      return of(void 0);
    }
    return this.http.delete<void>(`${this.base}/admin/webhooks/${id}`);
  }

  /** Latest delivery state per webhook. Needs P(`webhook.manage`). The overlay stays
   *  off, because the call only decorates the list. */
  listWebhookDeliveryStatus(): Observable<WebhookDeliveryStatus[]> {
    if (this.mock) return of([]);
    return this.http.get<WebhookDeliveryStatus[]>(
      `${this.base}/admin/webhooks/delivery-status`,
      { context: skipLoading() },
    );
  }

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

  /** Set a gremium role's granular permissions. */
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

  /**
   * Change the role or the term of office of one membership.
   *
   * The member and the Gremium stay immutable — a different member is a different
   * membership. The backend answers 409 when the new term overlaps another term of
   * the same member, and 422 when `validFrom` is not before `validUntil`.
   */
  updateGremiumMembership(
    id: Uuid,
    body: { gremiumRoleId?: Uuid; validFrom?: string | null; validUntil?: string | null },
  ): Observable<GremiumMembership> {
    return this.http.patch<GremiumMembership>(
      `${this.base}/admin/gremium-memberships/${id}`,
      body,
    );
  }

  deleteGremiumMembership(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/admin/gremium-memberships/${id}`);
  }

  // Every audit-log endpoint below needs P(audit.read).
  /** Keyset-paged audit log. `before` is the cursor (id). Filter by action, actor or time. */
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
    return this.http.get<AuditPage>(`${this.base}/admin/audit`, {
      params,
      context: skipLoading(),
    });
  }

  /** Distinct audit-log actors (for the actor filter). */
  listAuditActors(): Observable<AuditActor[]> {
    if (this.mock) return of([]);
    return this.http.get<AuditActor[]>(`${this.base}/admin/audit/actors`);
  }

  /** Revert a config change from the audit log (P `audit.revert`).
   *  Status 409 = a newer state exists or the change is not revertible.
   *  Status 404 = the entry or the revision is missing. */
  revertAuditEntry(entryId: number): Observable<AuditRevertResult> {
    return this.http.post<AuditRevertResult>(
      `${this.base}/admin/audit/${entryId}/revert`,
      {},
    );
  }

  /** Snapshots of a config entity (newest first) — version sidebar. */
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
      context: skipLoading(),
    });
  }

  /** Field diff of a snapshot against its predecessor (wire → array form). */
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
      .get<ConfigRevisionDiffWire>(`${this.base}/admin/config-revisions/${id}/diff`, {
        context: skipLoading(),
      })
      .pipe(map((w) => ({ ...w, diff: mapDiff(w.diff) })));
  }

  /** Restore an earlier snapshot as the new active version (sidebar restore). */
  restoreConfigRevision(id: Uuid): Observable<void> {
    return this.http.post<void>(
      `${this.base}/admin/config-revisions/${id}/restore`,
      {},
    );
  }

  // Every notification-config endpoint below needs P(admin.notifications).
  getNotificationSettings(): Observable<NotificationSettings> {
    if (this.mock) {
      return of({ taskReminderEnabled: true, taskReminderAfterDays: 5, taskReminderRepeatDays: 7 });
    }
    return this.http.get<NotificationSettings>(`${this.base}/admin/notification-settings`, {
      context: skipLoading(),
    });
  }

  putNotificationSettings(
    settings: Partial<NotificationSettings>,
  ): Observable<NotificationSettings> {
    return this.http.put<NotificationSettings>(
      `${this.base}/admin/notification-settings`,
      settings,
    );
  }

  // Every DSGVO/privacy endpoint below needs P(privacy.manage).
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

  // Backups (P backup.manage). The archive itself never passes through the browser
  // except as a signed download; these calls move metadata only.

  /** GET /admin/backups — the catalogue plus what this installation can do. */
  listBackups(): Observable<BackupList> {
    if (this.mock) {
      return of({
        items: structuredCopy(this.store.backups),
        enabled: true,
        restoreEnabled: true,
        retentionCount: 14,
      });
    }
    return this.http.get<BackupList>(`${this.base}/admin/backups`);
  }

  /** GET /admin/backups/{id} — one row. The page polls this while a job runs. */
  getBackup(id: Uuid): Observable<Backup> {
    if (this.mock) {
      const row = this.store.backups.find((b) => b.id === id);
      return of(structuredCopy(row ?? ({ id } as Backup)));
    }
    return this.http.get<Backup>(`${this.base}/admin/backups/${id}`, {
      // The poll runs on a timer, so it must not raise the global loading overlay.
      context: skipLoading(),
    });
  }

  /** POST /admin/backups — 202. The worker builds the archive. */
  createBackup(note?: string | null): Observable<Backup> {
    if (this.mock) {
      const row: Backup = {
        id: `b-${this.store.backups.length + 1}`,
        kind: 'manual',
        status: 'done',
        createdAt: new Date().toISOString(),
        finishedAt: new Date().toISOString(),
        sizeBytes: 12_582_912,
        objectCount: 8,
        note: note ?? null,
        pinned: false,
      };
      this.store.backups.unshift(row);
      return of(structuredCopy(row));
    }
    return this.http.post<Backup>(`${this.base}/admin/backups`, { note: note ?? null });
  }

  /** PATCH /admin/backups/{id} — edit the note, or pin against retention. */
  updateBackup(id: Uuid, patch: { note?: string | null; pinned?: boolean }): Observable<Backup> {
    if (this.mock) {
      const row = this.store.backups.find((b) => b.id === id);
      if (row) Object.assign(row, patch);
      return of(structuredCopy(row ?? ({ id } as Backup)));
    }
    return this.http.patch<Backup>(`${this.base}/admin/backups/${id}`, patch);
  }

  /** GET /admin/backups/{id}/export — a short-lived signed download URL. */
  exportBackup(id: Uuid): Observable<BackupExport> {
    if (this.mock) return of({ url: '#mock-archive', expiresIn: 300 });
    return this.http.get<BackupExport>(`${this.base}/admin/backups/${id}/export`);
  }

  /** POST /admin/backups/import — take an uploaded archive into the catalogue. */
  importBackup(file: File): Observable<Backup> {
    if (this.mock) return this.createBackup(file.name);
    const body = new FormData();
    body.append('file', file);
    return this.http.post<Backup>(`${this.base}/admin/backups/import`, body);
  }

  /**
   * POST /admin/backups/{id}/restore — 202. DESTRUCTIVE.
   *
   * The worker takes a `pre_restore` safety archive first, then replaces the database
   * and the attachment bucket. Everybody is logged out, the caller included, because
   * the session table comes from the archive too.
   */
  restoreBackup(id: Uuid): Observable<Backup> {
    if (this.mock) {
      const row = this.store.backups.find((b) => b.id === id);
      return of(structuredCopy(row ?? ({ id } as Backup)));
    }
    return this.http.post<Backup>(`${this.base}/admin/backups/${id}/restore`, {
      confirm: BACKUP_RESTORE_CONFIRMATION,
    });
  }

  /** DELETE /admin/backups/{id} — refused while the archive is pinned. */
  deleteBackup(id: Uuid): Observable<void> {
    if (this.mock) {
      this.store.backups = this.store.backups.filter((b) => b.id !== id);
      return of(void 0);
    }
    return this.http.delete<void>(`${this.base}/admin/backups/${id}`);
  }

  /** DSGVO data export (Art. 15) as an XLSX blob (by email). */
  downloadAuskunft(email: string): Observable<Blob> {
    if (this.mock) return of(new Blob([], { type: 'application/octet-stream' }));
    const params = new HttpParams().set('email', email);
    return this.http.get(`${this.base}/admin/privacy/auskunft`, {
      params,
      responseType: 'blob',
    });
  }

  getSiteConfig(): Observable<SiteConfig> {
    if (this.mock) return of(structuredCopy(this.store.site));
    return this.http.get<SiteConfig>(`${this.base}/admin/site-config`);
  }

  /** Save the draft (not yet active) — PUT /admin/site-config/draft. */
  saveBrandingDraft(draft: Branding): Observable<SiteConfig> {
    if (this.mock) {
      this.store.site.draft = structuredCopy(draft);
      this.store.site.hasDraftChanges = true;
      return of(structuredCopy(this.store.site));
    }
    return this.http.put<SiteConfig>(`${this.base}/admin/site-config/draft`, draft);
  }

  /** Activate the draft → new version — POST /admin/site-config/activate. */
  activateBranding(): Observable<SiteConfig> {
    if (this.mock) {
      this.store.site.active = structuredCopy(this.store.site.draft);
      this.store.site.version += 1;
      this.store.site.hasDraftChanges = false;
      return of(structuredCopy(this.store.site));
    }
    return this.http.post<SiteConfig>(`${this.base}/admin/site-config/activate`, {});
  }

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

/** Deep copy without assuming `structuredClone` is available (jsdom-safe). */
function structuredCopy<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/** Stable string hash for deterministic mock ids. It uses no `Math.random` and no `Date`. */
function hashString(value: string): number {
  let h = 0;
  for (let i = 0; i < value.length; i++) h = (Math.imul(31, h) + value.charCodeAt(i)) | 0;
  return h;
}

/**
 * Agent-token stubs for mock mode. The second row has no owner name and no expiry, so
 * the placeholder and the "never expires" rendering are visible without a backend.
 */
const MOCK_OAUTH_GRANTS: OAuthGrantAdmin[] = [
  {
    id: 'grant-1',
    principalId: 'p-1',
    principalName: 'Alex Admin',
    principalEmail: 'alex@stupa.example',
    clientId: 'antragsplattform-mcp',
    scope: 'mcp:read mcp:write',
    createdAt: '2026-06-01T10:00:00+00:00',
    accessExpiresAt: '2026-09-01T10:00:00+00:00',
    refreshExpiresAt: '2026-12-01T10:00:00+00:00',
  },
  {
    id: 'grant-2',
    principalId: 'p-2',
    principalName: null,
    principalEmail: null,
    clientId: 'antragsplattform-mcp',
    scope: 'mcp:read',
    createdAt: '2026-05-02T08:30:00+00:00',
    accessExpiresAt: null,
    refreshExpiresAt: null,
  },
];

/** CD-variant stubs for mock mode — the real list comes from the backend. */
const MOCK_CD_VARIANT_OPTIONS: CdVariantOption[] = [
  { id: 'cd-stupa', key: 'stupa', name: 'StuPa' },
  { id: 'cd-asta', key: 'asta', name: 'AStA' },
];

/** Application-type stubs for mock mode — real types come from the backend. */
const MOCK_APP_TYPE_OPTIONS: ApplicationTypeOption[] = [
  { id: '11111111-1111-1111-1111-111111111111', name: 'Finanzantrag' },
  { id: '22222222-2222-2222-2222-222222222222', name: 'Sonstiger Antrag' },
];

/** Minimal schema stub for mock mode (real schemas come from the backend). */
const MOCK_CONFIG_SCHEMAS: ConfigSchemas = {
  FormFieldDef: { title: 'FormFieldDef', type: 'object' },
  FlowGraph: { title: 'FlowGraph', type: 'object' },
};
