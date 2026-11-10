/**
 * § S/shared/api/000591 and § NF/compatibility/links/000592: every route is English, and an
 * old German URL reads as its English URL with the same ID, query and fragment.
 */
import type { Route } from '@angular/router';
import { routes } from '../../app.routes';
import { LEGACY_PATHS, LegacyUrlSerializer } from './legacy-url.serializer';

const serializer = new LegacyUrlSerializer();
const read = (url: string): string => serializer.serialize(serializer.parse(url));

const paths = (list: readonly Route[], base = ''): readonly string[] =>
  list.flatMap((r) => {
    const full = [base, r.path ?? ''].filter((p) => p !== '').join('/');
    return [full, ...paths(r.children ?? [], full)];
  });

describe('LegacyUrlSerializer', () => {
  it.each([
    ['/antrag/a1#t=tok', '/my-applications/a1#t=tok'],
    ['/antrag/a1', '/my-applications/a1'],
    ['/status?app=a1&t=tok', '/my-applications/a1#t=tok'],
    ['/status?app=a1', '/my-applications/a1'],
    ['/status', '/my-applications'],
    ['/protokolle', '/protocols'],
    ['/protokolle?gremium=g1&gremium=g2', '/protocols?committee=g1&committee=g2'],
    ['/protokolle/p1', '/protocols/p1'],
    ['/barrierefreiheit', '/accessibility'],
    ['/gremien', '/committees'],
    ['/gremien/g1?tab=mitglieder', '/committees/g1?tab=members'],
    ['/gremien/g1?tab=sitzungen', '/committees/g1?tab=meetings'],
    ['/gremien/g1?tab=anwesenheit', '/committees/g1?tab=attendance'],
    ['/gremien/g1?tab=beschluesse', '/committees/g1?tab=decisions'],
    ['/admin/gremien/g1/members', '/admin/committees/g1/members'],
    ['/admin/gremien/g1/roles', '/admin/committees/g1/roles'],
    ['/voting/beamer/m1?from=%2Fmeetings', '/voting/projector/m1?from=%2Fmeetings'],
    ['/voting?gremium=g1', '/voting?committee=g1'],
    ['/applications?gremium=g1&mine=true', '/applications?committee=g1&mine=true'],
    ['/budget?budget=b1&ks=k1&fy=f1', '/budget?budget=b1&costCentre=k1&fy=f1'],
  ])('reads %s as %s', (old, english) => {
    expect(read(old)).toBe(english);
  });

  it.each(['/committees/g1?tab=members', '/gremienx', '/my-applications/a1#t=tok', '/statusx', '/'])(
    'keeps %s',
    (url) => {
      expect(read(url)).toBe(url);
    },
  );

  it('has no route that holds an old German path', () => {
    const all = paths(routes).map((p) => `/${p}`);
    const old = LEGACY_PATHS.map(([o]) => o);
    expect(all.filter((p) => old.some((o) => p === o || p.startsWith(`${o}/`)))).toEqual([]);
    expect(all).not.toContain('/status');
  });
});
