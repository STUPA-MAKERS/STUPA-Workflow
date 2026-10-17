import { browserLabel, currentEnv, reportContext, viewportLabel, type ReportEnv } from './report-context';

const FIREFOX = 'Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0';
const CHROME =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36';
const EDGE = `${CHROME} Edg/130.0.0.0`;
const OPERA = `${CHROME} OPR/114.0.0.0`;
const SAFARI =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/19.0 Safari/605.1.15';
const IOS =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1';
const ANDROID =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36';
const CROS = 'Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36';

const ENV: ReportEnv = {
  href: 'https://stupa.example.org/status/A-1?token=secret#top',
  path: '/status/A-1',
  userAgent: FIREFOX,
  width: 1440,
  height: 900,
};

describe('reportContext', () => {
  it('drops the query and the fragment, because a status link carries its token there', () => {
    expect(reportContext(ENV, 'de', 'dark')).toEqual({
      url: 'https://stupa.example.org/status/A-1',
      route: '/status/A-1',
      userAgent: FIREFOX,
      viewport: '1440x900',
      language: 'de',
      colorScheme: 'dark',
    });
  });

  it('cuts every text to the cap of the server', () => {
    const long = 'x'.repeat(5000);
    const ctx = reportContext({ ...ENV, href: `https://a.example/${long}`, path: `/${long}`, userAgent: long }, 'en', 'light');
    expect(ctx.url).toHaveLength(2048);
    expect(ctx.route).toHaveLength(512);
    expect(ctx.userAgent).toHaveLength(512);
  });

  it('reads the current browser', () => {
    const env = currentEnv();
    expect(env.href).toBe(location.href);
    expect(env.path).toBe(location.pathname);
    expect(env.userAgent).toBe(navigator.userAgent);
    expect(env.width).toBe(window.innerWidth);
    expect(env.height).toBe(window.innerHeight);
  });
});

describe('browserLabel', () => {
  it.each([
    [FIREFOX, 'Firefox 131 · Linux'],
    [CHROME, 'Chrome 130 · Windows'],
    [EDGE, 'Edge 130 · Windows'],
    [OPERA, 'Opera 114 · Windows'],
    [SAFARI, 'Safari 19 · macOS'],
    [IOS, 'Safari 18 · iOS'],
    [ANDROID, 'Chrome 130 · Android'],
    [CROS, 'Chrome 130 · ChromeOS'],
  ])('names %s', (ua, label) => {
    expect(browserLabel(ua)).toBe(label);
  });

  it('names only the system when the browser is unknown', () => {
    expect(browserLabel('SomeBot/1.0 (Linux)')).toBe('Linux');
  });

  it('gives an unknown agent as it is', () => {
    expect(browserLabel('curl/8.5')).toBe('curl/8.5');
  });
});

describe('viewportLabel', () => {
  it('writes the size with a multiplication sign', () => {
    expect(viewportLabel('1440x900')).toBe('1440 × 900');
  });
});
