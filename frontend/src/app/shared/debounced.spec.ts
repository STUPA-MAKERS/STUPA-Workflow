import {
  EnvironmentInjector,
  Injector,
  createEnvironmentInjector,
  runInInjectionContext,
} from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { LIVE_SEARCH_DEBOUNCE_MS } from './live-search';
import { debounced } from './debounced';

describe('debounced', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  function make<A extends unknown[]>(fn: (...args: A) => void, ms?: number) {
    const injector = Injector.create({ providers: [], parent: TestBed.inject(Injector) });
    return runInInjectionContext(injector, () => debounced(fn, ms));
  }

  it('runs once after the pause, with the arguments of the last call', () => {
    const fn = jest.fn();
    const run = make((q: string) => fn(q));
    run('a');
    run('ab');
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS - 1);
    expect(fn).not.toHaveBeenCalled();
    jest.advanceTimersByTime(1);
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn).toHaveBeenCalledWith('ab');
    // The same call again runs again.
    run('ab');
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('takes its own pause and drops a cancelled call', () => {
    const fn = jest.fn();
    const run = make(fn, 50);
    run();
    run.cancel();
    jest.advanceTimersByTime(50);
    expect(fn).not.toHaveBeenCalled();
    run.cancel();
    run();
    jest.advanceTimersByTime(50);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('drops a waiting call when its injector is destroyed', () => {
    const fn = jest.fn();
    const injector = createEnvironmentInjector([], TestBed.inject(EnvironmentInjector));
    const run = runInInjectionContext(injector, () => debounced(fn));
    run();
    injector.destroy();
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
    expect(fn).not.toHaveBeenCalled();
  });
});
