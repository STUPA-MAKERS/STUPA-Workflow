import { Component, signal } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import { LONG_PRESS_MS, LongPressDirective } from './long-press.directive';

@Component({
  standalone: true,
  imports: [LongPressDirective],
  template: `
    <div data-testid="host" appLongPress [appLongPressOff]="off()" (appLongPress)="presses = presses + 1">
      <button data-testid="inner" type="button" (click)="clicks = clicks + 1">open</button>
    </div>
  `,
})
class HostComponent {
  readonly off = signal(false);
  presses = 0;
  clicks = 0;
}

function pointer(type: string, init: MouseEventInit & { isPrimary?: boolean } = {}): MouseEvent {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, ...init });
  if (init.isPrimary !== undefined) Object.defineProperty(event, 'isPrimary', { value: init.isPrimary });
  return event;
}

async function setup(off = false) {
  const { fixture } = await render(HostComponent);
  const host = fixture.componentInstance;
  host.off.set(off);
  fixture.detectChanges();
  return { host, fixture, el: screen.getByTestId('host'), inner: screen.getByTestId('inner') };
}

describe('LongPressDirective', () => {
  let vibrate: jest.Mock;
  beforeEach(() => {
    jest.useFakeTimers();
    vibrate = jest.fn();
    Object.defineProperty(navigator, 'vibrate', { value: vibrate, configurable: true });
  });
  afterEach(() => {
    jest.useRealTimers();
    Object.defineProperty(navigator, 'vibrate', { value: undefined, configurable: true });
  });

  it('emits after a long press, vibrates and swallows the click of the release', async () => {
    const { host, el, inner } = await setup();
    expect(el).toHaveClass('long-press');
    inner.dispatchEvent(pointer('pointerdown', { clientX: 10, clientY: 10 }));
    jest.advanceTimersByTime(LONG_PRESS_MS - 1);
    expect(host.presses).toBe(0);
    inner.dispatchEvent(pointer('pointermove', { clientX: 14, clientY: 14 }));
    jest.advanceTimersByTime(1);
    expect(host.presses).toBe(1);
    expect(vibrate).toHaveBeenCalledWith(10);
    inner.dispatchEvent(pointer('pointerup'));
    inner.click();
    expect(host.clicks).toBe(0);
    // The next tap opens again.
    inner.dispatchEvent(pointer('pointerdown'));
    inner.dispatchEvent(pointer('pointerup'));
    inner.click();
    expect(host.clicks).toBe(1);
  });

  it('forgets a long press whose release sends no click', async () => {
    const { host, inner } = await setup();
    inner.dispatchEvent(pointer('pointerdown'));
    jest.advanceTimersByTime(LONG_PRESS_MS);
    inner.dispatchEvent(pointer('pointerup'));
    jest.advanceTimersByTime(1000);
    inner.click();
    expect(host.clicks).toBe(1);
  });

  it('works without a vibration motor', async () => {
    Object.defineProperty(navigator, 'vibrate', { value: undefined, configurable: true });
    const { host, inner } = await setup();
    inner.dispatchEvent(pointer('pointerdown'));
    jest.advanceTimersByTime(LONG_PRESS_MS);
    expect(host.presses).toBe(1);
  });

  it('cancels on a drift, a scroll, an early release and a pointer cancel', async () => {
    const { host, inner } = await setup();
    inner.dispatchEvent(pointer('pointerdown', { clientX: 0, clientY: 0 }));
    inner.dispatchEvent(pointer('pointermove', { clientX: 9, clientY: 0 }));
    jest.advanceTimersByTime(LONG_PRESS_MS);

    inner.dispatchEvent(pointer('pointerdown'));
    document.body.dispatchEvent(new Event('scroll'));
    jest.advanceTimersByTime(LONG_PRESS_MS);

    inner.dispatchEvent(pointer('pointerdown'));
    jest.advanceTimersByTime(100);
    inner.dispatchEvent(pointer('pointerup'));
    jest.advanceTimersByTime(LONG_PRESS_MS);

    inner.dispatchEvent(pointer('pointerdown'));
    inner.dispatchEvent(pointer('pointercancel'));
    jest.advanceTimersByTime(LONG_PRESS_MS);
    expect(host.presses).toBe(0);
    // A move without a press does nothing.
    inner.dispatchEvent(pointer('pointermove', { clientX: 50 }));
    inner.click();
    expect(host.clicks).toBe(1);
  });

  it('captures the pointer on the pressed element and stops when the pointer leaves the host', async () => {
    const { host, el, inner } = await setup();
    const capture = jest.fn();
    Object.defineProperty(inner, 'setPointerCapture', { value: capture, configurable: true });
    const down = pointer('pointerdown');
    Object.defineProperty(down, 'pointerId', { value: 7 });
    inner.dispatchEvent(down);
    expect(capture).toHaveBeenCalledWith(7);
    el.dispatchEvent(new MouseEvent('pointerleave'));
    jest.advanceTimersByTime(LONG_PRESS_MS);
    expect(host.presses).toBe(0);
    // A capture that the browser refuses still lets the press run.
    Object.defineProperty(inner, 'setPointerCapture', {
      value: () => {
        throw new DOMException('no pointer', 'NotFoundError');
      },
      configurable: true,
    });
    inner.dispatchEvent(pointer('pointerdown'));
    jest.advanceTimersByTime(LONG_PRESS_MS);
    expect(host.presses).toBe(1);
  });

  it('ignores a secondary button and a pointer that is not the primary one', async () => {
    const { host, inner } = await setup();
    inner.dispatchEvent(pointer('pointerdown', { button: 2 }));
    jest.advanceTimersByTime(LONG_PRESS_MS);
    inner.dispatchEvent(pointer('pointerdown', { isPrimary: false }));
    jest.advanceTimersByTime(LONG_PRESS_MS);
    expect(host.presses).toBe(0);
  });

  it('opens from the context menu, once per press', async () => {
    const { host, inner } = await setup();
    const menu = pointer('contextmenu');
    inner.dispatchEvent(menu);
    expect(menu.defaultPrevented).toBe(true);
    expect(host.presses).toBe(1);
    // A touch press: the menu of the browser comes before the timer, then after it.
    inner.dispatchEvent(pointer('pointerdown'));
    inner.dispatchEvent(pointer('contextmenu'));
    expect(host.presses).toBe(2);
    jest.advanceTimersByTime(LONG_PRESS_MS);
    inner.dispatchEvent(pointer('contextmenu'));
    expect(host.presses).toBe(2);
    // A key resets the press, so Enter opens the card.
    inner.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    inner.click();
    expect(host.clicks).toBe(1);
  });

  it('does nothing while off', async () => {
    const { host, el, inner } = await setup(true);
    expect(el).not.toHaveClass('long-press');
    inner.dispatchEvent(pointer('pointerdown'));
    jest.advanceTimersByTime(LONG_PRESS_MS);
    const menu = pointer('contextmenu');
    inner.dispatchEvent(menu);
    expect(menu.defaultPrevented).toBe(false);
    expect(host.presses).toBe(0);
  });

  it('stops a running press when the host goes', async () => {
    const { host, fixture, inner } = await setup();
    inner.dispatchEvent(pointer('pointerdown'));
    fixture.destroy();
    jest.advanceTimersByTime(LONG_PRESS_MS);
    expect(host.presses).toBe(0);
  });
});
