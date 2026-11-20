import { DOCUMENT } from '@angular/common';
import { TestBed } from '@angular/core/testing';
import { PageResumeService, RESUME_FOLD_MS } from './page-resume.service';

/** The page returns from the background (§F/meetings/meetings/001739). */
describe('PageResumeService', () => {
  let doc: Document;
  let state: DocumentVisibilityState;
  let count: number;

  const setVisibility = (next: DocumentVisibilityState): void => {
    state = next;
    doc.dispatchEvent(new Event('visibilitychange'));
  };
  const pageShow = (persisted: boolean): void => {
    const ev = new Event('pageshow') as PageTransitionEvent;
    Object.defineProperty(ev, 'persisted', { value: persisted });
    doc.defaultView?.dispatchEvent(ev);
  };

  beforeEach(() => {
    jest.useFakeTimers();
    doc = TestBed.inject(DOCUMENT);
    state = 'visible';
    jest.spyOn(doc, 'visibilityState', 'get').mockImplementation(() => state);
    count = 0;
    TestBed.inject(PageResumeService).resume$.subscribe(() => (count += 1));
  });

  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  it('emits when the hidden page becomes visible again, not on a visible event alone', () => {
    setVisibility('visible');
    expect(count).toBe(0);
    setVisibility('hidden');
    expect(count).toBe(0);
    setVisibility('visible');
    expect(count).toBe(1);
  });

  it('emits on a restore from the back-forward cache and on online, not on a fresh pageshow', () => {
    pageShow(false);
    expect(count).toBe(0);
    pageShow(true);
    expect(count).toBe(1);
    jest.advanceTimersByTime(RESUME_FOLD_MS);
    doc.defaultView?.dispatchEvent(new Event('online'));
    expect(count).toBe(2);
  });

  it('folds the events of one return into one value', () => {
    setVisibility('hidden');
    setVisibility('visible');
    pageShow(true);
    doc.defaultView?.dispatchEvent(new Event('online'));
    expect(count).toBe(1);
    jest.advanceTimersByTime(RESUME_FOLD_MS);
    setVisibility('hidden');
    setVisibility('visible');
    expect(count).toBe(2);
  });
});
