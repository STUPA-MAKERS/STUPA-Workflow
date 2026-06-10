import { LoadingService } from './loading.service';

/**
 * Deterministische Test-Uhr: ersetzt setTimeout/Date.now durch eine manuelle
 * Zeitachse — frei von jest-Fake-Timer/zone.js-Wechselwirkungen.
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
    svc.advance(150);
    expect(svc.visible()).toBe(true);
  });

  it('keeps visible until all requests finish, then hides after min duration', () => {
    svc.inc();
    svc.inc();
    svc.advance(150);
    expect(svc.visible()).toBe(true);

    svc.dec(); // one still running
    svc.advance(500);
    expect(svc.visible()).toBe(true);

    svc.dec(); // none running → hide after MIN_VISIBLE (elapsed already > min here)
    expect(svc.visible()).toBe(false);
  });

  it('enforces a minimum visible duration to avoid flicker', () => {
    svc.inc();
    svc.advance(150); // visible now (shownAt = 150)
    svc.dec(); // finishes immediately after showing
    expect(svc.visible()).toBe(true); // must stay for the min window
    svc.advance(399);
    expect(svc.visible()).toBe(true);
    svc.advance(1);
    expect(svc.visible()).toBe(false);
  });

  it('cancels the pending hide when a new request starts', () => {
    svc.inc();
    svc.advance(150);
    svc.dec(); // schedule hide
    svc.advance(200);
    svc.inc(); // new request → cancel hide
    svc.advance(400);
    expect(svc.visible()).toBe(true);
  });
});
