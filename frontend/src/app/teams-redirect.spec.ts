/**
 * § F/collaboration/teams/003072: the tab Gremien is the tab Teams. `/committees` leads to
 * `/teams`, and an old link to a Gremium leads to the list with `?gremium=`, which opens the
 * inherent team.
 */
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { type Route, Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { routes } from './app.routes';

@Component({ changeDetection: ChangeDetectionStrategy.OnPush, standalone: true, template: '<p>Teams</p>' })
class TeamsStub {}

const shell = routes.find((r) => r.children?.some((c) => c.path === 'teams'));
const redirects: Route[] = (shell?.children ?? []).filter((r) => r.path?.startsWith('committees'));

describe('the old route /committees (003072)', () => {
  async function open(url: string): Promise<string> {
    TestBed.configureTestingModule({
      providers: [provideRouter([...redirects, { path: 'teams', component: TeamsStub, children: [] }])],
    });
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl(url);
    return TestBed.inject(Router).url;
  }

  it('has the two redirects in the shell', () => {
    expect(redirects.map((r) => r.path)).toEqual(['committees', 'committees/:id']);
  });

  it('opens /committees as /teams', async () => {
    expect(await open('/committees')).toBe('/teams');
  });

  it('opens a Gremium as the list that finds its team', async () => {
    expect(await open('/committees/g-1')).toBe('/teams?gremium=g-1');
  });
});
