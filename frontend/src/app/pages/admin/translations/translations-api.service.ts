import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import { skipLoading } from '@stupa-makers/ui-kit';

/** An extra UI language as the admin page lists it (P admin.translations). */
export interface AdminUiLanguage {
  readonly code: string;
  readonly name: string;
  readonly active: boolean;
  readonly updatedAt?: string | null;
}

/** The overrides of one locale: key → text. A key without an override is absent. */
export interface LocaleTexts {
  readonly locale: string;
  readonly overrides: Record<string, string>;
}

/**
 * The admin routes of the UI texts (`/admin/translations`, P admin.translations). A save
 * sends only the changed keys: a text sets the override, `null` restores the built-in text.
 */
@Injectable({ providedIn: 'root' })
export class TranslationsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${inject(API_BASE_URL)}/admin/translations`;

  languages(): Observable<AdminUiLanguage[]> {
    return this.http.get<AdminUiLanguage[]>(`${this.base}/languages`, { context: skipLoading() });
  }

  createLanguage(body: { code: string; name: string }): Observable<AdminUiLanguage> {
    return this.http.post<AdminUiLanguage>(`${this.base}/languages`, body);
  }

  updateLanguage(code: string, body: { name?: string; active?: boolean }): Observable<AdminUiLanguage> {
    return this.http.patch<AdminUiLanguage>(`${this.base}/languages/${encodeURIComponent(code)}`, body);
  }

  deleteLanguage(code: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/languages/${encodeURIComponent(code)}`);
  }

  texts(locale: string): Observable<LocaleTexts> {
    return this.http.get<LocaleTexts>(`${this.base}/texts/${encodeURIComponent(locale)}`, {
      context: skipLoading(),
    });
  }

  saveTexts(locale: string, changes: Record<string, string | null>): Observable<LocaleTexts> {
    return this.http.put<LocaleTexts>(`${this.base}/texts/${encodeURIComponent(locale)}`, { changes });
  }
}
