import { Component, signal } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { RangeChipComponent, type RangeKind, type RangeValue } from './range-chip.component';

@Component({
  standalone: true,
  imports: [RangeChipComponent],
  template: `
    <app-range-chip
      label="Betrag"
      [kind]="kind()"
      [from]="from()"
      [to]="to()"
      (applied)="onApplied($event)"
    />
  `,
})
class HostComponent {
  readonly kind = signal<RangeKind>('amount');
  readonly from = signal('');
  readonly to = signal('');
  readonly applied: RangeValue[] = [];
  onApplied(v: RangeValue): void {
    this.applied.push(v);
    this.from.set(v.from);
    this.to.set(v.to);
  }
}

/** Let `matchMedia` report a phone (or not). jsdom has none of its own. */
function mockPhone(phone: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: phone && query.includes('max-width'),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia;
}
const realMatchMedia = window.matchMedia;
afterEach(() => {
  window.matchMedia = realMatchMedia;
});

async function setup(opts: { phone?: boolean; kind?: RangeKind; from?: string; to?: string } = {}) {
  localStorage.setItem('ap.locale', 'de');
  mockPhone(!!opts.phone);
  const view = await render(HostComponent);
  const host = view.fixture.componentInstance;
  host.kind.set(opts.kind ?? 'amount');
  host.from.set(opts.from ?? '');
  host.to.set(opts.to ?? '');
  view.fixture.detectChanges();
  const chip = () => view.container.querySelector('.rc__chip') as HTMLButtonElement;
  const text = () => (chip().textContent ?? '').replace(/\s+/g, ' ').trim();
  const cmp = view.fixture.debugElement.children[0].componentInstance as RangeChipComponent;
  return { view, host, chip, text, cmp, user: userEvent.setup() };
}

describe('RangeChipComponent', () => {
  it('shows the label without a range and the range with one', async () => {
    const { host, chip, text, view } = await setup();
    expect(chip().textContent?.trim()).toBe('Betrag');
    expect(chip().classList.contains('on')).toBe(false);

    host.from.set('100');
    host.to.set('500.5');
    view.fixture.detectChanges();
    expect(text()).toContain('Betrag: 100,00 € – 500,50 €');
    expect(chip().classList.contains('on')).toBe(true);

    host.to.set('');
    view.fixture.detectChanges();
    expect(text()).toContain('Betrag: ab 100,00 €');

    host.from.set('');
    host.to.set('20');
    view.fixture.detectChanges();
    expect(text()).toContain('Betrag: bis 20,00 €');

    // A value that is no number stays as typed.
    host.from.set('x');
    view.fixture.detectChanges();
    expect(text()).toContain('x – 20,00 €');
  });

  it('formats a date range', async () => {
    const { text } = await setup({ kind: 'date', from: '2026-09-01', to: '2026-09-30' });
    expect(text()).toContain('01.09.2026 – 30.09.2026');
  });

  it('keeps a date it cannot read as typed', async () => {
    const { text } = await setup({ kind: 'date', from: 'bald' });
    expect(text()).toContain('ab bald');
  });

  it('opens a sheet on a draft and applies it', async () => {
    const { chip, cmp, host, view, user } = await setup({ from: '10' });
    await user.click(chip());
    expect(chip().getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByRole('dialog', { name: 'Betrag' })).toBeInTheDocument();

    // The draft starts at the current range; a typed draft changes nothing yet.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = cmp as any;
    expect(c.draftFrom()).toBe('10');
    c.draftTo.set('50');
    expect(host.applied).toEqual([]);

    cmp.apply();
    view.fixture.detectChanges();
    expect(host.applied).toEqual([{ from: '10', to: '50' }]);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('refuses a start after the end and says why', async () => {
    const { chip, cmp, host, view, user } = await setup();
    await user.click(chip());
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = cmp as any;
    c.draftFrom.set('90');
    c.draftTo.set('10');
    view.fixture.detectChanges();
    expect(screen.getByRole('alert').textContent).toContain('Anfang liegt nach dem Ende');
    cmp.apply();
    expect(host.applied).toEqual([]);

    c.kind = () => 'date';
    c.draftFrom.set('2026-10-01');
    c.draftTo.set('2026-09-01');
    expect(c.draftValid()).toBe(false);
  });

  it('resets both bounds at once', async () => {
    const { chip, cmp, host, view, user } = await setup({ kind: 'date', from: '2026-09-01' });
    await user.click(chip());
    cmp.reset();
    view.fixture.detectChanges();
    expect(host.applied).toEqual([{ from: '', to: '' }]);
    expect(chip().textContent?.trim()).toBe('Betrag');
  });

  it('runs the buttons of the sheet and shows date fields for a date range', async () => {
    const { chip, host, user, view } = await setup({ kind: 'date' });
    await user.click(chip());
    expect(view.container.ownerDocument.querySelectorAll('app-datepicker').length).toBe(2);
    await user.click(screen.getByRole('button', { name: 'Anwenden' }));
    expect(host.applied).toEqual([{ from: '', to: '' }]);
    await user.click(chip());
    await user.click(screen.getByRole('button', { name: 'Zurücksetzen' }));
    expect(host.applied.length).toBe(2);
  });

  it('opens a popover under the chip on a wide screen, not a sheet', async () => {
    const { chip, user } = await setup();
    await user.click(chip());
    expect(document.querySelector('.rc__pop')).not.toBeNull();
    expect(document.querySelector('.ss--start')).toBeNull();
    expect(screen.getByRole('dialog', { name: 'Betrag' }).classList.contains('rc__pop')).toBe(true);
    // A second click on the chip closes it again.
    await user.click(chip());
    expect(document.querySelector('.rc__pop')).toBeNull();
  });

  it('closes the popover on Escape and on a click outside, and keeps the range', async () => {
    const { chip, host, user, view } = await setup({ from: '10' });
    await user.click(chip());
    await user.keyboard('{Escape}');
    expect(document.querySelector('.rc__pop')).toBeNull();
    expect(document.activeElement).toBe(chip());

    await user.click(chip());
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    view.fixture.detectChanges();
    expect(document.querySelector('.rc__pop')).toBeNull();
    expect(host.applied).toEqual([]);
  });

  it('keeps the popover open on a click inside it', async () => {
    const { chip, user, view } = await setup();
    await user.click(chip());
    const pop = document.querySelector('.rc__pop') as HTMLElement;
    pop.dispatchEvent(new Event('pointerdown', { bubbles: true }));
    view.fixture.detectChanges();
    expect(document.querySelector('.rc__pop')).not.toBeNull();
  });

  it('comes from the bottom on a phone, in the top layer', async () => {
    const shown: Element[] = [];
    const proto = HTMLElement.prototype as HTMLElement & { showPopover?: () => void };
    const real = proto.showPopover;
    proto.showPopover = function (this: HTMLElement) {
      shown.push(this);
    };
    try {
      const { chip, user, view } = await setup({ phone: true });
      // Closed, the sheet is not in the chip row at all.
      expect(document.querySelector('.rc__layer')).toBeNull();
      await user.click(chip());
      await new Promise((r) => setTimeout(r));
      view.fixture.detectChanges();
      const layer = document.querySelector('.rc__layer') as HTMLElement;
      // A chip row that scrolls clips its children: the sheet goes to the top layer.
      expect(layer.getAttribute('popover')).toBe('manual');
      expect(shown).toContain(layer);
      expect(layer.querySelector('.ss--bottom')).not.toBeNull();
      expect(document.querySelector('.rc__pop')).toBeNull();

      await user.keyboard('{Escape}');
      view.fixture.detectChanges();
      expect(document.querySelector('.rc__layer')).toBeNull();
      expect(chip().getAttribute('aria-expanded')).toBe('false');
    } finally {
      proto.showPopover = real;
    }
  });

  it('keeps the popover under its chip when the chip moves', async () => {
    const frames: FrameRequestCallback[] = [];
    const realRaf = window.requestAnimationFrame;
    window.requestAnimationFrame = (cb: FrameRequestCallback) => frames.push(cb);
    try {
      const { chip, user, view } = await setup();
      let left = 347;
      chip().getBoundingClientRect = () =>
        ({ left, right: left + 100, top: 140, bottom: 172, width: 100, height: 32, x: left, y: 140 }) as DOMRect;
      await user.click(chip());
      await new Promise((r) => setTimeout(r));
      view.fixture.detectChanges();
      const pop = () => document.querySelector('.rc__pop') as HTMLElement;
      expect(pop().style.left).toBe('347px');
      expect(pop().style.top).toBe('176px');

      // A chip before it appears: the chip moves right, and the popover goes with it.
      left = 500;
      frames.splice(0).forEach((cb) => cb(0));
      view.fixture.detectChanges();
      expect(pop().style.left).toBe('500px');

      // Closed, it checks no more.
      await user.click(chip());
      frames.splice(0).forEach((cb) => cb(0));
      expect(frames.length).toBe(0);
    } finally {
      window.requestAnimationFrame = realRaf;
    }
  });
});
