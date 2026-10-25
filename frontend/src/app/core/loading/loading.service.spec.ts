import { LoadingService } from './loading.service';

/**
 * Deterministic test clock. It replaces setTimeout and Date.now with a manual
 * time axis, free of side effects between the jest fake timers and zone.js.
 */
class TestLoadingService extends LoadingService {
  private time = 0;
  private seq = 0;
  private timers: { id: number; due: number; fn: () => void }[] = [];

  protected override now(): number {
    return this.time;
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  protected override setTimer(fn: () => void, ms: number): any {
    const id = ++this.seq;
    this.timers.push({ id, due: this.time + ms, fn });
    return id;
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  protected override clearTimer(id: any): void {
    this.timers = this.timers.filter((t) => t.id !== id);
  }

  advance(ms: number): void {
    this.time += ms;
    const due = this.timers.filter((t) => t.due <= this.time);
    this.timers = this.timers.filter((t) => t.due > this.time);
    for (const t of due) t.fn();
  }
}

describe('LoadingService', () => {
  let svc: TestLoadingService;
  beforeEach(() => (svc = new TestLoadingService()));

  it('stays hidden for fast requests (finish before the show delay)', () => {
    svc.inc();
    svc.advance(100);
    svc.dec();
    svc.advance(500);
    expect(svc.visible()).toBe(false);
  });

  it('shows after the delay while a request is in flight', () => {
    svc.inc();
    expect(svc.visible()).toBe(false);
    svc.advance(300);
    expect(svc.visible()).toBe(true);
  });

  /**
   * When no request runs, the hide comes after MIN_VISIBLE; the elapsed time is already above the
   * minimum.
   */
  it('keeps visible until all requests finish, then hides after min duration', () => {
    svc.inc();
    svc.inc();
    svc.advance(300);
    expect(svc.visible()).toBe(true);

    svc.dec();
    svc.advance(500);
    expect(svc.visible()).toBe(true);

    svc.dec();
    expect(svc.visible()).toBe(false);
  });

  /** A request that finishes right after the show must stay for the minimum window. */
  it('enforces a minimum visible duration to avoid flicker', () => {
    svc.inc();
    svc.advance(300);
    svc.dec();
    expect(svc.visible()).toBe(true);
    svc.advance(399);
    expect(svc.visible()).toBe(true);
    svc.advance(1);
    expect(svc.visible()).toBe(false);
  });

  it('cancels the pending hide when a new request starts', () => {
    svc.inc();
    svc.advance(300);
    svc.dec();
    svc.advance(200);
    svc.inc();
    svc.advance(400);
    expect(svc.visible()).toBe(true);
  });
});
