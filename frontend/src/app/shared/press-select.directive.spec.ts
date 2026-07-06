import { Component } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import { PressSelectDirective } from './press-select.directive';

@Component({
  standalone: true,
  imports: [PressSelectDirective],
  template: `
    <div
      data-testid="card"
      appPressSelect
      [appPressSelectEnabled]="enabled"
      [appPressSelectActive]="active"
      (appPressSelectToggle)="toggles = toggles + 1"
    >
      <button data-testid="inner" type="button">action</button>
      <span data-testid="text">text</span>
    </div>
  `,
})
class HostComponent {
  enabled = true;
  active = false;
  toggles = 0;
}

/** matchMedia stub: `(pointer: coarse)` matches iff `coarse` is true. */
function mockPointer(coarse: boolean): void {
  (window as { matchMedia: unknown }).matchMedia = jest.fn().mockImplementation((query: string) => ({
    matches: coarse && query.includes('coarse'),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}

function pointer(type: string, x = 0, y = 0): MouseEvent {
  return new MouseEvent(type, { clientX: x, clientY: y, bubbles: true, cancelable: true });
}

async function setup(opts: { coarse?: boolean; enabled?: boolean; active?: boolean } = {}): Promise<{
  host: HostComponent;
  card: HTMLElement;
  detect: () => void;
}> {
  mockPointer(opts.coarse ?? true);
  const { fixture } = await render(HostComponent);
  const host = fixture.componentInstance;
  host.enabled = opts.enabled ?? true;
  host.active = opts.active ?? false;
  fixture.detectChanges();
  return { host, card: screen.getByTestId('card'), detect: () => fixture.detectChanges() };
}

describe('PressSelectDirective', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it('long press emits one toggle and swallows the follow-up click', async () => {
    const { host, card } = await setup();
    card.dispatchEvent(pointer('pointerdown', 10, 10));
    jest.advanceTimersByTime(450);
    expect(host.toggles).toBe(1);
    // The click fired after releasing the long press must NOT re-toggle.
    card.dispatchEvent(pointer('click', 10, 10));
    expect(host.toggles).toBe(1);
  });

  it('does not emit when released before the hold delay', async () => {
    const { host, card } = await setup();
    card.dispatchEvent(pointer('pointerdown'));
    jest.advanceTimersByTime(200);
    card.dispatchEvent(pointer('pointerup'));
    jest.advanceTimersByTime(1000);
    expect(host.toggles).toBe(0);
  });

  it('cancels the press when the finger drifts (scroll intent)', async () => {
    const { host, card } = await setup();
    card.dispatchEvent(pointer('pointerdown', 0, 0));
    card.dispatchEvent(pointer('pointermove', 0, 30));
    jest.advanceTimersByTime(1000);
    expect(host.toggles).toBe(0);
  });

  it('keeps the press within the drift threshold', async () => {
    const { host, card } = await setup();
    card.dispatchEvent(pointer('pointerdown', 0, 0));
    card.dispatchEvent(pointer('pointermove', 4, 4));
    jest.advanceTimersByTime(450);
    expect(host.toggles).toBe(1);
  });

  it('a plain tap toggles only while select mode is active', async () => {
    const { host, card, detect } = await setup({ active: false });
    card.dispatchEvent(pointer('click'));
    expect(host.toggles).toBe(0);
    host.active = true;
    detect();
    card.dispatchEvent(pointer('click'));
    expect(host.toggles).toBe(1);
  });

  it('never reacts to interactive children (button)', async () => {
    const { host } = await setup({ active: true });
    const inner = screen.getByTestId('inner');
    inner.dispatchEvent(pointer('pointerdown'));
    jest.advanceTimersByTime(1000);
    inner.dispatchEvent(pointer('click'));
    expect(host.toggles).toBe(0);
  });

  it('is inert on fine-pointer devices', async () => {
    const fine = await setup({ coarse: false, active: true });
    fine.card.dispatchEvent(pointer('pointerdown'));
    jest.advanceTimersByTime(1000);
    fine.card.dispatchEvent(pointer('click'));
    expect(fine.host.toggles).toBe(0);
  });

  it('is inert when disabled', async () => {
    const disabled = await setup({ enabled: false, active: true });
    disabled.card.dispatchEvent(pointer('pointerdown'));
    jest.advanceTimersByTime(1000);
    disabled.card.dispatchEvent(pointer('click'));
    expect(disabled.host.toggles).toBe(0);
  });

  it('suppresses the context menu on touch while enabled', async () => {
    const { card } = await setup();
    const ev = pointer('contextmenu');
    card.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
  });
});
