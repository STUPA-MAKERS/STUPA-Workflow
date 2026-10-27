import type { TicketContext } from '@core/api/tickets.service';

/** The parts of the browser the context reads; a spec passes its own. */
export interface ReportEnv {
  href: string;
  path: string;
  userAgent: string;
  width: number;
  height: number;
}

/** The current browser, read when the dialog opens. */
export function currentEnv(): ReportEnv {
  return {
    href: location.href,
    path: location.pathname,
    userAgent: navigator.userAgent,
    width: window.innerWidth,
    height: window.innerHeight,
  };
}

/** Cut a text to the cap of the server. */
function cap(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) : text;
}

/**
 * The technical context of a ticket: the page, the browser, the window, the language
 * and the colour scheme. The query string and the fragment stay out of the url and the
 * route, because a status link carries its token there.
 */
export function reportContext(
  env: ReportEnv,
  language: string,
  colorScheme: 'light' | 'dark',
): TicketContext {
  const url = env.href.split(/[?#]/)[0];
  return {
    url: cap(url, 2048),
    route: cap(env.path, 512),
    userAgent: cap(env.userAgent, 512),
    viewport: `${env.width}x${env.height}`,
    language,
    colorScheme,
  };
}

const BROWSERS: readonly [RegExp, string][] = [
  [/Edg\/(\d+)/, 'Edge'],
  [/OPR\/(\d+)/, 'Opera'],
  [/Firefox\/(\d+)/, 'Firefox'],
  [/Chrome\/(\d+)/, 'Chrome'],
  [/Version\/(\d+)[\d.]* (?:Mobile\/\S+ )?Safari/, 'Safari'],
];

const SYSTEMS: readonly [RegExp, string][] = [
  [/Android/, 'Android'],
  [/iPhone|iPad|iPod/, 'iOS'],
  [/Windows/, 'Windows'],
  [/Mac OS X|Macintosh/, 'macOS'],
  [/CrOS/, 'ChromeOS'],
  [/Linux/, 'Linux'],
];

/**
 * A short name of the browser for people: "Firefox 131 · Linux". An unknown agent
 * gives the raw string.
 */
export function browserLabel(userAgent: string): string {
  const browser = BROWSERS.map(([re, name]) => {
    const m = re.exec(userAgent);
    return m ? `${name} ${m[1]}` : null;
  }).find((b) => b !== null);
  const system = SYSTEMS.find(([re]) => re.test(userAgent))?.[1];
  if (!browser && !system) return userAgent;
  return [browser, system].filter(Boolean).join(' · ');
}

/** "1440x900" as "1440 × 900". */
export function viewportLabel(viewport: string): string {
  return viewport.replace('x', ' × ');
}
