import type { Branding } from './admin.models';
import { brandingLinkErrors, isAllowedLinkUrl } from './branding.util';

describe('isAllowedLinkUrl', () => {
  it('accepts http(s) and mailto', () => {
    expect(isAllowedLinkUrl('https://example.org')).toBe(true);
    expect(isAllowedLinkUrl('http://example.org/x')).toBe(true);
    expect(isAllowedLinkUrl('mailto:support@example.org')).toBe(true);
  });

  it('rejects javascript:, data: and other schemes', () => {
    expect(isAllowedLinkUrl('javascript:alert(1)')).toBe(false);
    expect(isAllowedLinkUrl('data:text/html,<script>')).toBe(false);
    expect(isAllowedLinkUrl('ftp://example.org')).toBe(false);
    expect(isAllowedLinkUrl('vbscript:msgbox(1)')).toBe(false);
  });

  it('rejects empty and relative URLs', () => {
    expect(isAllowedLinkUrl('')).toBe(false);
    expect(isAllowedLinkUrl('   ')).toBe(false);
    expect(isAllowedLinkUrl(null)).toBe(false);
    expect(isAllowedLinkUrl('/relative/path')).toBe(false);
  });
});

describe('brandingLinkErrors', () => {
  function branding(footerUrl: string, legalUrl: string): Branding {
    return {
      logos: {},
      footerColumns: [{ label: { de: 'x' }, links: [{ label: { de: 'l' }, url: footerUrl }] }],
      copyright: { de: '©' },
      legalLinks: [{ label: { de: 'p' }, url: legalUrl }],
      freetexts: { loginHint: {}, welcome: {}, support: {}, emailFooter: {} },
    };
  }

  it('returns no errors when all links are safe', () => {
    expect(brandingLinkErrors(branding('https://a.org', 'mailto:a@b.org'))).toEqual([]);
  });

  it('collects unsafe footer and legal links', () => {
    const errs = brandingLinkErrors(branding('javascript:1', 'data:x'));
    expect(errs).toContain('javascript:1');
    expect(errs).toContain('data:x');
  });
});
