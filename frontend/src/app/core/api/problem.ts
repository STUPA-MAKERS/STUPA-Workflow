/**
 * Read a failed request. The API answers every error as problem+json (RFC 9457), and
 * `HttpClient` puts that body on `HttpErrorResponse.error`. These readers take `unknown`,
 * so a `catchError` or a subscribe `error` callback can pass its argument as it is. A
 * missing or malformed field gives the empty value, never an exception.
 */

/** The body of a failed request, or null when the error carries no object body. */
function problemBody(err: unknown): Record<string, unknown> | null {
  if (typeof err !== 'object' || err === null || !('error' in err)) return null;
  const body = (err as { error: unknown }).error;
  return typeof body === 'object' && body !== null ? (body as Record<string, unknown>) : null;
}

/** The stable problem+json `code` of a failed request (for example `open_vote`), or `''`. */
export function problemCode(err: unknown): string {
  const code = problemBody(err)?.['code'];
  return typeof code === 'string' ? code : '';
}

/** The problem+json `detail` text of a failed request, or `''`. */
export function problemDetail(err: unknown): string {
  const detail = problemBody(err)?.['detail'];
  return typeof detail === 'string' ? detail : '';
}

/** The HTTP status of a failed request, or 0 when the error carries none. */
export function errorStatus(err: unknown): number {
  if (typeof err !== 'object' || err === null || !('status' in err)) return 0;
  const status = Number((err as { status: unknown }).status);
  return Number.isFinite(status) ? status : 0;
}
