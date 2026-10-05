import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { BEAMER_FROM_PARAM, beamerOrigin, beamerUrl } from './beamer-link.util';

describe('beamer link', () => {
  it('names the current page as the origin', () => {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    const router = TestBed.inject(Router);
    const tree = beamerUrl(router, 'm-1');
    expect(router.serializeUrl(tree)).toBe('/voting/beamer/m-1?from=%2F');
    expect(tree.queryParamMap.get(BEAMER_FROM_PARAM)).toBe('/');
  });

  it.each([
    ['/meetings/m-1', '/meetings/m-1'],
    ['/meetings?sel=m-1', '/meetings?sel=m-1'],
    [null, null],
    ['', null],
    ['meetings', null],
    ['https://evil.example', null],
    ['//evil.example', null],
    ['/\\evil.example', null],
    ['/voting/beamer/m-1', null],
  ])('accepts %p as origin: %p', (from, expected) => {
    expect(beamerOrigin(from)).toBe(expected);
  });
});
