import { Injectable, inject } from '@angular/core';
import { type Observable, catchError, shareReplay, throwError } from 'rxjs';
import { AdminApiService } from '../admin-api.service';
import type { AuditChainCheck } from '../admin.models';

/**
 * The live check of the audit chain for the "Zustand" tiles, at most one time per session.
 *
 * The tiles check the chain live only before the first stored check. A live check reads
 * the whole chain again, so the tiles must not repeat it each time they are made again
 * (a return to `/admin`). The first result stays for the session. A failed check does not
 * stay, so the next visit tries again.
 */
@Injectable({ providedIn: 'root' })
export class AuditLiveCheckService {
  private readonly api = inject(AdminApiService);
  private run$: Observable<AuditChainCheck> | null = null;

  check(): Observable<AuditChainCheck> {
    if (!this.run$) {
      this.run$ = this.api.verifyAuditChain().pipe(
        catchError((err: unknown) => {
          this.run$ = null;
          return throwError(() => err);
        }),
        shareReplay({ bufferSize: 1, refCount: false }),
      );
    }
    return this.run$;
  }
}
