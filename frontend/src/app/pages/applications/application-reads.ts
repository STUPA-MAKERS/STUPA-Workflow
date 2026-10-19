import { inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { Uuid } from '@core/api/models';
import { TodosApiService } from '@core/api/todos.service';
import { AuthService } from '@core/auth/auth.service';

/**
 * The reads that `ApplicationsDetailComponent` makes when an application opens, for the
 * read ahead of a list (`prefetchDetails`): the application, its form, versions,
 * comments, timeline, transitions (with the right to fire them), files and linked
 * to-dos. It injects its services, so it runs in an injection context, as the `reads` of
 * `prefetchDetails` do.
 */
export function applicationReads(id: Uuid): Observable<unknown>[] {
  const api = inject(ApiClient);
  const todos = inject(TodosApiService);
  return [
    api.getApplication(id, { quiet: true, detail: true }),
    api.applicationForm(id, { detail: true }),
    api.versions(id, { detail: true }),
    api.comments(id, { quiet: true, detail: true }),
    api.timeline(id, { quiet: true, detail: true }),
    ...(inject(AuthService).can('application.transition') ? [api.transitions(id, { detail: true })] : []),
    api.listAttachments(id),
    todos.linked('application', id),
  ];
}
