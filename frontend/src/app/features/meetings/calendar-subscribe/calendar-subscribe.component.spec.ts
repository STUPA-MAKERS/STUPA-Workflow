import { Component, viewChild } from '@angular/core';
import { fireEvent, render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Subject, of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { CalendarFeed } from '@core/api/models';
import { MEDIA } from '@stupa-makers/ui-kit';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
import { COPIED_MS, CalendarSubscribeComponent } from './calendar-subscribe.component';

@Component({
  standalone: true,
  imports: [CalendarSubscribeComponent],
  template: `
    <button type="button" class="anchor" (click)="abo.toggle($event.currentTarget)">Abo</button>
    <button type="button" class="outside">Draußen</button>
    <app-calendar-subscribe #abo />
  `,
})
class Host {
  readonly abo = viewChild.required(CalendarSubscribeComponent);
}

const URL = 'https://x/api/calendar/TOK.ics';

async function setup(
  opts: { feed?: () => ReturnType<ApiClient['myCalendar']>; rotate?: () => ReturnType<ApiClient['rotateCalendar']> } = {},
) {
  localStorage.setItem('ap.locale', 'de');
  const api = {
    myCalendar: jest.fn(opts.feed ?? (() => of<CalendarFeed>({ url: URL }))),
    rotateCalendar: jest.fn(opts.rotate ?? (() => of<CalendarFeed>({ url: 'https://x/api/calendar/NEW.ics' }))),
  };
  const view = await render(Host, { providers: [{ provide: ApiClient, useValue: api }] });
  const anchor = screen.getByRole('button', { name: 'Abo' });
  const openIt = async () => {
    await userEvent.click(anchor);
    await view.fixture.whenStable();
    view.fixture.detectChanges();
  };
  return { ...view, api, anchor, openIt, cmp: view.fixture.componentInstance.abo() };
}

describe('CalendarSubscribeComponent', () => {
  let restore: (() => void) | null = null;
  afterEach(() => {
    restore?.();
    restore = null;
    localStorage.clear();
  });

  it('reads the feed on the first opening only and shows the URL in full', async () => {
    const { api, openIt, cmp, fixture } = await setup();
    expect(api.myCalendar).not.toHaveBeenCalled();
    await openIt();
    const dialog = screen.getByRole('dialog', { name: 'Kalender-Abo' });
    expect(dialog).toHaveTextContent(URL);
    cmp.close();
    fixture.detectChanges();
    expect(screen.queryByRole('dialog')).toBeNull();
    await openIt();
    expect(api.myCalendar).toHaveBeenCalledTimes(1);
  });

  it('copies the URL', async () => {
    const writeText = jest.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    const { openIt, fixture } = await setup();
    await openIt();
    await userEvent.click(screen.getByRole('button', { name: 'Kopieren' }));
    await fixture.whenStable();
    fixture.detectChanges();
    expect(writeText).toHaveBeenCalledWith(URL);
    expect(screen.getByRole('button', { name: 'Kopiert!' })).toBeInTheDocument();
  });

  it('reads "Kopieren" again after a short time', async () => {
    const writeText = jest.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    const { openIt, fixture, cmp } = await setup();
    await openIt();
    jest.useFakeTimers();
    try {
      cmp.copy();
      await Promise.resolve();
      await Promise.resolve();
      expect(cmp.copied()).toBe(true);
      // A second copy starts the time again.
      cmp.copy();
      await Promise.resolve();
      await Promise.resolve();
      jest.advanceTimersByTime(COPIED_MS - 1);
      expect(cmp.copied()).toBe(true);
      jest.advanceTimersByTime(1);
      expect(cmp.copied()).toBe(false);
      cmp.copy();
      await Promise.resolve();
      await Promise.resolve();
      fixture.destroy();
      jest.advanceTimersByTime(COPIED_MS);
    } finally {
      jest.useRealTimers();
    }
  });

  it('forgets "copied" when the clipboard refuses, and does nothing without a URL', async () => {
    const writeText = jest.fn(() => Promise.reject(new Error('denied')));
    Object.assign(navigator, { clipboard: { writeText } });
    const { openIt, fixture, cmp } = await setup();
    await openIt();
    await userEvent.click(screen.getByRole('button', { name: 'Kopieren' }));
    await fixture.whenStable();
    expect(cmp.copied()).toBe(false);
    cmp.url.set(null);
    cmp.copy();
    expect(writeText).toHaveBeenCalledTimes(1);
  });

  it('asks before it makes a new URL, and can be cancelled', async () => {
    const { openIt, api, fixture } = await setup();
    await openIt();
    await userEvent.click(screen.getByRole('button', { name: 'Neue URL erzeugen' }));
    fixture.detectChanges();
    expect(screen.getByText('Erzeugt eine neue URL — die bisherige wird ungültig.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    fixture.detectChanges();
    expect(api.rotateCalendar).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Neue URL erzeugen' }));
    fixture.detectChanges();
    const confirm = screen.getByRole('group', { name: 'Neue URL erzeugen' });
    await userEvent.click(confirm.querySelector('app-button[variant="danger"] button') as HTMLElement);
    fixture.detectChanges();
    expect(api.rotateCalendar).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('dialog')).toHaveTextContent('https://x/api/calendar/NEW.ics');
    expect(screen.queryByRole('group')).toBeNull();
  });

  it('creates the first link from the empty state, once at a time', async () => {
    const answer = new Subject<CalendarFeed>();
    const { openIt, api, fixture, cmp } = await setup({
      feed: () => of({ url: null }),
      rotate: () => answer,
    });
    await openIt();
    expect(screen.getByText('Es wurde noch kein Abo-Link erzeugt.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Abo-Link erzeugen' }));
    cmp.rotate();
    expect(api.rotateCalendar).toHaveBeenCalledTimes(1);
    answer.next({ url: URL });
    fixture.detectChanges();
    expect(screen.getByRole('dialog')).toHaveTextContent(URL);
  });

  it('says when the feed cannot be read, and reads it again', async () => {
    let fail = true;
    const { openIt, api, fixture } = await setup({
      feed: () => (fail ? throwError(() => new Error('boom')) : of({ url: URL })),
    });
    await openIt();
    expect(screen.getByRole('alert')).toHaveTextContent('Der Abo-Link konnte nicht geladen werden.');
    fail = false;
    await userEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    fixture.detectChanges();
    expect(api.myCalendar).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByRole('dialog')).toHaveTextContent(URL);
  });

  it('says when a new URL fails and keeps the old one', async () => {
    const { openIt, fixture, cmp } = await setup({ rotate: () => throwError(() => new Error('nope')) });
    await openIt();
    cmp.askRotate();
    cmp.rotate();
    fixture.detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent('Der Abo-Link konnte nicht erzeugt werden.');
    expect(cmp.busy()).toBe(false);
    expect(cmp.error()).toBe(false);
    expect(screen.getByRole('dialog')).toHaveTextContent(URL);
    // A new opening starts without the old message.
    cmp.close();
    await openIt();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('closes on Escape and on a press outside, and returns the focus to the anchor', async () => {
    const { openIt, anchor, fixture, cmp } = await setup();
    await openIt();
    const dialog = screen.getByRole('dialog');
    fireEvent.keyDown(dialog, { key: 'Enter' });
    expect(cmp.isOpen()).toBe(true);
    fireEvent.keyDown(dialog, { key: 'Escape' });
    fixture.detectChanges();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(anchor).toHaveFocus();

    await openIt();
    fireEvent.pointerDown(screen.getByRole('dialog'));
    expect(cmp.isOpen()).toBe(true);
    fireEvent.pointerDown(anchor);
    expect(cmp.isOpen()).toBe(true);
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Draußen' }));
    fixture.detectChanges();
    expect(screen.queryByRole('dialog')).toBeNull();
    // Closing a closed popover changes nothing.
    cmp.close();
    expect(cmp.isOpen()).toBe(false);
  });

  it('toggles with the anchor and keeps its place on a resize', async () => {
    const { openIt, anchor, fixture } = await setup();
    await openIt();
    window.dispatchEvent(new Event('resize'));
    expect(parseFloat(document.querySelector<HTMLElement>('.cs--pop')!.style.top)).toBeGreaterThanOrEqual(0);
    await userEvent.click(anchor);
    fixture.detectChanges();
    expect(screen.queryByRole('dialog')).toBeNull();
    window.dispatchEvent(new Event('resize'));
  });

  it('opens above the anchor when it does not fit below', async () => {
    const { openIt, anchor } = await setup();
    const rect = (top: number, h: number) =>
      ({ top, bottom: top + h, left: 900, right: 940, width: 40, height: h, x: 900, y: top }) as DOMRect;
    jest.spyOn(anchor, 'getBoundingClientRect').mockReturnValue(rect(700, 40));
    const original = HTMLElement.prototype.getBoundingClientRect;
    jest
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockImplementation(function (this: HTMLElement) {
        return this.classList.contains('cs--pop') ? rect(0, 300) : original.call(this);
      });
    await openIt();
    expect(document.querySelector<HTMLElement>('.cs--pop')!.style.top).toBe(`${700 - 6 - 300}px`);
    jest.restoreAllMocks();
  });

  it('shows a bottom sheet on a phone, and closes with it', async () => {
    restore = matchMediaQueries(MEDIA.phone);
    const { fixture, cmp } = await setup();
    cmp.open();
    await new Promise((r) => setTimeout(r));
    fixture.detectChanges();
    const sheet = screen.getByRole('dialog', { name: 'Kalender-Abo' });
    expect(sheet).toHaveTextContent(URL);
    // A press anywhere is the sheet's business, not the popover's.
    fireEvent.pointerDown(document.body);
    expect(cmp.isOpen()).toBe(true);
    window.dispatchEvent(new Event('resize'));
    await userEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    fixture.detectChanges();
    expect(cmp.isOpen()).toBe(false);
    fixture.destroy();
  });

  it('opens without an anchor under itself, survives an early resize and a quick second call', async () => {
    const shown: HTMLElement[] = [];
    Object.defineProperty(HTMLElement.prototype, 'showPopover', {
      configurable: true,
      value(this: HTMLElement) {
        shown.push(this);
      },
    });
    try {
      const { fixture, cmp } = await setup();
      cmp.open();
      cmp.open();
      // Before the popover rendered there is nothing to place.
      window.dispatchEvent(new Event('resize'));
      fixture.detectChanges();
      await new Promise((r) => setTimeout(r));
      expect(shown).toHaveLength(1);
      expect(shown[0]).toHaveClass('cs--pop');
      fireEvent.pointerDown(document.body);
      expect(cmp.isOpen()).toBe(false);
      // The sheet only reports a close.
      cmp.onSheetOpen(true);
      cmp.open();
      fixture.destroy();
    } finally {
      delete (HTMLElement.prototype as { showPopover?: unknown }).showPopover;
    }
  });

  it('swaps the popover and the sheet on a resize across the phone limit while open', async () => {
    let listener: ((e: { matches: boolean }) => void) | null = null;
    const original = window.matchMedia;
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        addEventListener: (_: string, fn: (e: { matches: boolean }) => void) => {
          if (query === MEDIA.phone) listener = fn;
        },
        removeEventListener: () => {},
      }),
    });
    const shown: HTMLElement[] = [];
    Object.defineProperty(HTMLElement.prototype, 'showPopover', {
      configurable: true,
      value(this: HTMLElement) {
        shown.push(this);
      },
    });
    try {
      const { fixture, cmp } = await setup();
      // Closed: a resize changes nothing.
      listener!({ matches: true });
      fixture.detectChanges();
      listener!({ matches: false });
      fixture.detectChanges();
      cmp.open();
      fixture.detectChanges();
      await new Promise((r) => setTimeout(r));
      expect(shown.at(-1)).toHaveClass('cs--pop');
      listener!({ matches: true });
      fixture.detectChanges();
      await new Promise((r) => setTimeout(r));
      expect(shown.at(-1)).toHaveClass('cs__layer');
      listener!({ matches: false });
      fixture.detectChanges();
      await new Promise((r) => setTimeout(r));
      expect(shown.at(-1)).toHaveClass('cs--pop');
      expect(shown).toHaveLength(3);
      fixture.destroy();
    } finally {
      delete (HTMLElement.prototype as { showPopover?: unknown }).showPopover;
      Object.defineProperty(window, 'matchMedia', { writable: true, value: original });
    }
  });

  it('does not show a popover that is already open', async () => {
    const show = jest.fn();
    Object.defineProperty(HTMLElement.prototype, 'showPopover', { configurable: true, value: show });
    const original = Element.prototype.matches;
    const matches = jest
      .spyOn(Element.prototype, 'matches')
      .mockImplementation(function (this: Element, sel: string) {
        return sel === ':popover-open' || original.call(this, sel);
      });
    try {
      const { fixture, cmp } = await setup();
      cmp.open();
      fixture.detectChanges();
      await new Promise((r) => setTimeout(r));
      expect(show).not.toHaveBeenCalled();
      fixture.destroy();
    } finally {
      matches.mockRestore();
      delete (HTMLElement.prototype as { showPopover?: unknown }).showPopover;
    }
  });

  it('is placed under its anchor on the first rendered frame, with no timer', async () => {
    const rect = (x: number, y: number, w: number, h: number) =>
      ({ top: y, bottom: y + h, left: x, right: x + w, width: w, height: h, x, y }) as DOMRect;
    const atShow: { placed: boolean; top: string }[] = [];
    Object.defineProperty(HTMLElement.prototype, 'showPopover', {
      configurable: true,
      value(this: HTMLElement) {
        atShow.push({ placed: this.classList.contains('cs--placed'), top: this.style.top });
      },
    });
    const original = HTMLElement.prototype.getBoundingClientRect;
    const spy = jest
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockImplementation(function (this: HTMLElement) {
        if (this.classList.contains('cs--pop')) return rect(0, 0, 400, 300);
        if (this.classList.contains('anchor')) return rect(900, 100, 40, 40);
        return original.call(this);
      });
    try {
      const { fixture, anchor } = await setup();
      fireEvent.click(anchor);
      // One change detection, no timer and no further tick: the popover is in the top
      // layer, hidden until placed, and placed under the end of its anchor.
      fixture.detectChanges();
      const pop = document.querySelector<HTMLElement>('.cs--pop')!;
      expect(atShow).toEqual([{ placed: false, top: '' }]);
      expect(pop).toHaveClass('cs--placed');
      expect(pop.style.top).toBe(`${100 + 40 + 6}px`);
      expect(pop.style.left).toBe(`${940 - 400}px`);
      expect(pop).toHaveFocus();
      fixture.destroy();
    } finally {
      spy.mockRestore();
      delete (HTMLElement.prototype as { showPopover?: unknown }).showPopover;
    }
  });

  it('places the popover again when the layout changes, and stops on close', async () => {
    const observers: { cb: () => void; targets: Element[]; disconnect: jest.Mock }[] = [];
    const originalRO = (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
      readonly entry: { cb: () => void; targets: Element[]; disconnect: jest.Mock };
      constructor(cb: () => void) {
        this.entry = { cb, targets: [], disconnect: jest.fn() };
        observers.push(this.entry);
      }
      observe(el: Element): void {
        this.entry.targets.push(el);
      }
      disconnect(): void {
        this.entry.disconnect();
      }
    };
    let anchorTop = 100;
    const original = HTMLElement.prototype.getBoundingClientRect;
    const spy = jest
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockImplementation(function (this: HTMLElement) {
        if (this.classList.contains('anchor'))
          return { top: anchorTop, bottom: anchorTop + 40, left: 900, right: 940, width: 40, height: 40, x: 900, y: anchorTop } as DOMRect;
        return original.call(this);
      });
    try {
      const { openIt, fixture, cmp, anchor } = await setup();
      await openIt();
      expect(observers).toHaveLength(1);
      const [ro] = observers;
      // The popover, the anchor and each container of the anchor, not the page: on a
      // pane page the body never changes size.
      expect(ro.targets.slice(0, 3)).toEqual([document.querySelector('.cs--pop'), anchor, anchor.parentElement]);
      expect(ro.targets).not.toContain(document.body);
      const top = () => document.querySelector<HTMLElement>('.cs--pop')!.style.top;
      expect(top()).toBe('146px');
      // The calendar grid renders below the toolbar and moves the anchor.
      anchorTop = 160;
      ro.cb();
      expect(top()).toBe('206px');
      cmp.close();
      fixture.detectChanges();
      expect(ro.disconnect).toHaveBeenCalled();
      // A late callback after the close places nothing.
      const pop = document.querySelector<HTMLElement>('.cs--pop');
      anchorTop = 300;
      ro.cb();
      expect(pop?.style.top ?? '206px').toBe('206px');
      fixture.destroy();
    } finally {
      spy.mockRestore();
      (globalThis as { ResizeObserver?: unknown }).ResizeObserver = originalRO;
    }
  });

  it('observes the containers of the anchor up to main, and only the popover without one', async () => {
    const observers: { targets: Element[] }[] = [];
    const originalRO = (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
      readonly entry = { targets: [] as Element[] };
      constructor() {
        observers.push(this.entry);
      }
      observe(el: Element): void {
        this.entry.targets.push(el);
      }
      disconnect(): void {}
    };
    const outer = document.createElement('div');
    const main = document.createElement('main');
    const row = document.createElement('div');
    const anchor = document.createElement('button');
    outer.append(main);
    main.append(row);
    row.append(anchor);
    document.body.append(outer);
    try {
      const { cmp, fixture } = await setup();
      cmp.open(anchor);
      fixture.detectChanges();
      await fixture.whenStable();
      expect(observers.at(-1)!.targets).toEqual([document.querySelector('.cs--pop'), anchor, row, main]);
      cmp.close(false);
      fixture.detectChanges();
      cmp.open();
      fixture.detectChanges();
      await fixture.whenStable();
      expect(observers.at(-1)!.targets).toEqual([document.querySelector('.cs--pop')]);
      fixture.destroy();
    } finally {
      outer.remove();
      (globalThis as { ResizeObserver?: unknown }).ResizeObserver = originalRO;
    }
  });
});
