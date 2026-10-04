import { offerHref } from './positions';

describe('offerHref', () => {
  it.each([
    ['https://example.com/a?b=1', 'https://example.com/a?b=1'],
    ['  http://example.com  ', 'http://example.com/'],
    ['HTTPS://EXAMPLE.COM/x', 'https://example.com/x'],
  ])('links %s', (label, href) => {
    expect(offerHref(label)).toBe(href);
  });

  it.each(['Studierendenwerk', '', 'ftp://example.com', 'javascript:alert(1)', 'https://a b.de', 'http://'])(
    'does not link %s',
    (label) => {
      expect(offerHref(label)).toBeNull();
    },
  );
});
