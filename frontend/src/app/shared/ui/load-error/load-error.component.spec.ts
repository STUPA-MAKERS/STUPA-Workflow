import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { render } from '@testing-library/angular';
import { ServerReachabilityService } from '@core/api/server-reachability.service';
import { runAxe } from '../../../../testing/a11y';
import { loadErrorToast, retryLoadError } from '../../../../testing/load-error';
import { LoadErrorComponent } from './load-error.component';

const TOAST_TIME = 60_000;

function reachMock() {
  const waiting = signal(false);
  const state = signal<'up' | 'checking' | 'down'>('up');
  return { waiting, state };
}

async function setup(reach = reachMock(), show = true) {
  const retry = jest.fn();
  const view = await render(
    `@if (show) { <app-load-error message="Anträge konnten nicht geladen werden." (retry)="retry()" /> }`,
    {
      imports: [LoadErrorComponent],
      componentProperties: { retry, show },
      providers: [{ provide: ServerReachabilityService, useValue: reach }],
    },
  );
  return { ...view, retry, reach };
}

describe('LoadErrorComponent', () => {
  afterEach(() => jest.useRealTimers());

  /** § 000576: a toast with the retry action, nothing in the page. */
  it('shows the error as a toast with "Erneut versuchen" and renders nothing', async () => {
    const { container, retry } = await setup();
    expect(loadErrorToast()).toBe('Anträge konnten nicht geladen werden.');
    expect(container.querySelector('app-load-error')?.textContent).toBe('');
    retryLoadError();
    expect(retry).toHaveBeenCalledTimes(1);
    expect(loadErrorToast()).toBeNull();
  });

  it('adds nothing to the page that axe can flag', async () => {
    const { container } = await setup();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  /** § 000577: the toast does not close by its time, and closes when the error goes. */
  it('keeps the toast past its time and closes it when the content loads', async () => {
    jest.useFakeTimers();
    const view = await setup();
    jest.advanceTimersByTime(TOAST_TIME);
    expect(loadErrorToast()).not.toBeNull();
    view.rerender({ componentProperties: { show: false, retry: view.retry } });
    expect(loadErrorToast()).toBeNull();
  });

  /** § 000579: no toast while the server is unreachable, and a new load once it is back. */
  it('shows no toast while the server is unreachable and loads again when it is back', async () => {
    const reach = reachMock();
    reach.waiting.set(true);
    reach.state.set('down');
    const { retry, fixture } = await setup(reach);
    expect(loadErrorToast()).toBeNull();
    reach.waiting.set(false);
    reach.state.set('up');
    fixture.detectChanges();
    TestBed.tick();
    expect(retry).toHaveBeenCalledTimes(1);
    expect(loadErrorToast()).toBeNull();
  });

  /** § 000579: a check that finds the server there shows the toast after all. */
  it('shows the toast when the check finds the server there', async () => {
    const reach = reachMock();
    reach.waiting.set(true);
    reach.state.set('checking');
    const { retry, fixture } = await setup(reach);
    expect(loadErrorToast()).toBeNull();
    reach.waiting.set(false);
    reach.state.set('up');
    fixture.detectChanges();
    TestBed.tick();
    expect(retry).not.toHaveBeenCalled();
    expect(loadErrorToast()).toBe('Anträge konnten nicht geladen werden.');
  });

  it('hides the toast when the server goes away after the error', async () => {
    const { reach, fixture } = await setup();
    expect(loadErrorToast()).not.toBeNull();
    reach.waiting.set(true);
    reach.state.set('down');
    fixture.detectChanges();
    TestBed.tick();
    expect(loadErrorToast()).toBeNull();
  });
});
