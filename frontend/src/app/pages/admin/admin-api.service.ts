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
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { type Observable, of } from 'rxjs';
import { API_BASE_URL, USE_MOCK_API } from '@core/api/api.config';
import type { Uuid } from '@core/api/models';
import type { FormFieldDef } from '@core/api/models';
import {
  type Branding,
  type FlowGraph,
  type FormOverviewItem,
  type Gremium,
  type NotificationRule,
  type Role,
  type SiteConfig,
  type WebhookConfig,
} from './admin.models';
import {
  MOCK_BRANDING,
  MOCK_FORMS,
  MOCK_GREMIEN,
  MOCK_NOTIFICATION_RULES,
  MOCK_WEBHOOKS,
} from './admin.mock';

/** JSON-Schema-Export des Backends (`export_json_schemas`, config_schemas). */
export type ConfigSchemas = Record<string, Record<string, unknown>>;

@Injectable({ providedIn: 'root' })
export class AdminApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);
  private readonly mock = inject(USE_MOCK_API);

  // In-Memory-Store (nur Mock-Modus). Pro Service-Instanz, reicht für UI/Tests.
  private readonly store = {
    gremien: structuredCopy(MOCK_GREMIEN),
    webhooks: structuredCopy(MOCK_WEBHOOKS),
    rules: structuredCopy(MOCK_NOTIFICATION_RULES),
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

  listRoles(): Observable<Role[]> {
    if (this.mock) return of([]);
    return this.http.get<Role[]>(`${this.base}/admin/roles`);
  }

  /** Überblick aktiver Formulare (#75): Name/Gremium/Status/Version. */
  listForms(): Observable<FormOverviewItem[]> {
    if (this.mock) return of(structuredCopy(MOCK_FORMS));
    return this.http.get<FormOverviewItem[]>(`${this.base}/admin/application-types`);
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

/** Minimaler Schema-Stub für den Mock-Modus (echte Schemas kommen vom Backend). */
const MOCK_CONFIG_SCHEMAS: ConfigSchemas = {
  FormFieldDef: { title: 'FormFieldDef', type: 'object' },
  FlowGraph: { title: 'FlowGraph', type: 'object' },
};
