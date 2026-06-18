import { type HttpInterceptorFn, HttpContext, HttpContextToken } from '@angular/common/http';
import { inject } from '@angular/core';
import { finalize } from 'rxjs';
import { LoadingService } from './loading.service';

/**
 * Per-Request-Opt-out für den globalen Ladebildschirm (#loading). `true` ⇒ dieser
 * Request zählt **nicht** in den Overlay-Zähler.
 */
export const SKIP_LOADING = new HttpContextToken<boolean>(() => false);

/** Fertiger {@link HttpContext}, der den globalen Ladebildschirm unterdrückt. */
export function skipLoading(): HttpContext {
  return new HttpContext().set(SKIP_LOADING, true);
}

/**
 * Speist den globalen Ladebildschirm (#loading) über den {@link LoadingService}.
 *
 * Der Overlay soll **nur erscheinen, wenn Daten geladen werden** — daher zählen
 * ausschließlich **GET**-Requests, und nur solange sie nicht per
 * {@link SKIP_LOADING} ausgeklinkt sind:
 *
 * - **Mutationen** (POST/PUT/PATCH/DELETE) lösen den Overlay nie aus — sie haben
 *   lokales Feedback (Button-`loading`, optimistische Updates) und sollen die
 *   Sicht nicht aufblitzen lassen (Autosave, Vote, Reorder, Finalize …).
 * - **Hintergrund-GETs** (Status-Polls, Refresh nach Mutation/WS-Event, debounced
 *   Typeahead) **und** Loads, die bereits einen **lokalen** Spinner zeigen, setzen
 *   `SKIP_LOADING` und überspringen den Overlay — so stapeln sich nicht zwei
 *   Spinner.
 *
 * Als **äußerster** Interceptor registriert, damit die volle Request-Dauer
 * (inkl. Auth/Mock) erfasst wird.
 */
export const loadingInterceptor: HttpInterceptorFn = (req, next) => {
  if (req.method !== 'GET' || req.context.get(SKIP_LOADING)) {
    return next(req);
  }
  const loading = inject(LoadingService);
  loading.inc();
  return next(req).pipe(finalize(() => loading.dec()));
};
