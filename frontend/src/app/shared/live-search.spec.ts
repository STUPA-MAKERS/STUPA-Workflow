import { EnvironmentInjector, createEnvironmentInjector } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Subject, of, throwError, type Observable } from 'rxjs';
import { LIVE_SEARCH_DEBOUNCE_MS, liveSearch, type LiveSearchOptions } from './live-search';

/** A search in its own injector, so a test can destroy it. */
function make<T>(options: LiveSearchOptions<T>) {
  const injector = createEnvironmentInjector([], TestBed.inject(EnvironmentInjector));
  const search = injector.runInContext(() => liveSearch(options));
  return { search, injector };
}

describe('liveSearch', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it('debounces the typing into one request', () => {
    const run = jest.fn((q: string) => of([q]));
    const result = jest.fn();
    const { search } = make({ run, result });
    search.set('ab');
    search.set('abc');
    search.set('abcd');
    expect(search.text()).toBe('abcd');
    expect(search.pending()).toBe(true);
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS - 1);
    expect(run).not.toHaveBeenCalled();
    jest.advanceTimersByTime(1);
    expect(run).toHaveBeenCalledTimes(1);
    expect(run).toHaveBeenCalledWith('abcd');
    expect(result).toHaveBeenCalledWith(['abcd'], 'abcd');
    expect(search.applied()).toBe('abcd');
    expect(search.pending()).toBe(false);
  });

  it('cancels the request that is still out when the query changes', () => {
    const answers = new Map<string, Subject<string>>();
    const run = jest.fn((q: string): Observable<string> => {
      const s = new Subject<string>();
      answers.set(q, s);
      return s;
    });
    const result = jest.fn();
    const { search } = make({ run, result });
    search.set('ab');
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
    search.set('abcd');
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
    // The late answer to "ab" arrives after the request for "abcd" went out.
    answers.get('ab')!.next('old');
    expect(answers.get('ab')!.observed).toBe(false);
    expect(result).not.toHaveBeenCalled();
    answers.get('abcd')!.next('new');
    expect(result).toHaveBeenCalledTimes(1);
    expect(result).toHaveBeenCalledWith('new', 'abcd');
  });

  it('trims, skips a short query and does not repeat the query on screen', () => {
    const run = jest.fn((q: string) => of(q));
    const { search } = make({ run });
    search.set(' a ');
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
    expect(run).not.toHaveBeenCalled();
    search.set(' kim ');
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
    expect(run).toHaveBeenLastCalledWith('kim');
    search.set('kim  ');
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
    expect(run).toHaveBeenCalledTimes(1);
    expect(search.pending()).toBe(false);
  });

  it('runs the empty query at once when there is no reset', () => {
    const run = jest.fn((q: string) => of(q));
    const { search } = make({ run });
    search.set('kim');
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
    search.clear();
    expect(search.text()).toBe('');
    expect(run).toHaveBeenLastCalledWith('');
    expect(search.applied()).toBe('');
  });

  it('resets at once and cancels a waiting search on clear', () => {
    const run = jest.fn((q: string) => of(q));
    const reset = jest.fn();
    const { search } = make({ run, reset });
    search.set('kim');
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
    search.set('kimb');
    search.clear();
    expect(reset).toHaveBeenCalledTimes(1);
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
    expect(run).toHaveBeenCalledTimes(1);
    expect(search.pending()).toBe(false);
    expect(search.applied()).toBe('');
  });

  it('runs at once on flush and again on refresh', () => {
    const run = jest.fn((q: string) => of(q));
    const { search } = make({ run });
    search.set('kim');
    search.flush();
    expect(run).toHaveBeenCalledWith('kim');
    search.refresh();
    expect(run).toHaveBeenCalledTimes(2);
  });

  it('takes a text from outside without a search', () => {
    const run = jest.fn((q: string) => of(q));
    const { search } = make({ run });
    search.set('ab');
    search.sync('Kim Meyer');
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
    expect(run).not.toHaveBeenCalled();
    expect(search.text()).toBe('Kim Meyer');
    expect(search.applied()).toBe('Kim Meyer');
  });

  it('reports a failure and keeps searching', () => {
    const run = jest
      .fn<Observable<string>, [string]>()
      .mockReturnValueOnce(throwError(() => new Error('x')))
      .mockReturnValue(of('ok'));
    const error = jest.fn();
    const result = jest.fn();
    const { search } = make({ run, error, result });
    search.set('ab');
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
    expect(error).toHaveBeenCalledWith(expect.any(Error), 'ab');
    expect(search.pending()).toBe(false);
    search.set('abc');
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
    expect(result).toHaveBeenCalledWith('ok', 'abc');
  });

  it('settles a search without a request at once', () => {
    const run = jest.fn();
    const { search } = make<void>({ run, minLength: 0, debounceMs: 100 });
    search.set('k');
    jest.advanceTimersByTime(100);
    expect(run).toHaveBeenCalledWith('k');
    expect(search.applied()).toBe('k');
    expect(search.pending()).toBe(false);
  });

  it('stops with its injector', () => {
    const run = jest.fn((q: string) => of(q));
    const { search, injector } = make({ run });
    search.set('kim');
    injector.destroy();
    jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
    expect(run).not.toHaveBeenCalled();
  });
});
