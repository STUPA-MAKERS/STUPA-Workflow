/**
 * The build ID of this frontend (§ 002150). `deploy/web/Dockerfile` replaces the value with
 * a hash of the frontend sources before `npm run build`, and writes the same hash into the
 * nginx header `X-App-Version`. A local build keeps `dev`, and `dev` never reloads.
 */
export const APP_BUILD_ID = 'dev';
