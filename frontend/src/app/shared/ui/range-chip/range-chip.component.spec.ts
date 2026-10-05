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

  it('comes from the bottom on a phone', async () => {
    const { chip, user } = await setup({ phone: true });
    await user.click(chip());
    expect(document.querySelector('.ss--bottom')).not.toBeNull();
  });
});
