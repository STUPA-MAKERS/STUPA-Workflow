import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { closeOnBack } from './close-on-back';

@Component({ template: '' })
class HostComponent {
  readonly open = signal(false);
  readonly closes = signal(0);

  constructor() {
    closeOnBack(this.open, () => {
      this.closes.update((n) => n + 1);
      this.open.set(false);
    });
  }
}

/** Wait for the `popstate` event that follows a step in the history. */
function popped(): Promise<void> {
  return new Promise((resolve) => window.addEventListener('popstate', () => resolve(), { once: true }));
}

describe('closeOnBack', () => {
  function setup() {
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    return fixture;
  }

  it('§NF/usability/controls/000931: an open dialog is an entry in the history, and "back" closes it', async () => {
    const fixture = setup();
    const before = window.history.length;
    fixture.componentInstance.open.set(true);
    fixture.detectChanges();
    expect(window.history.length).toBe(before + 1);
    const pop = popped();
    window.history.back();
    await pop;
    expect(fixture.componentInstance.closes()).toBe(1);
    expect(fixture.componentInstance.open()).toBe(false);
  });

  it('§NF/usability/controls/000931: a close by a button takes the entry away and calls nothing', async () => {
    const fixture = setup();
    const push = jest.spyOn(window.history, 'pushState');
    fixture.componentInstance.open.set(true);
    fixture.detectChanges();
    expect(push).toHaveBeenCalledTimes(1);
    const pop = popped();
    fixture.componentInstance.open.set(false);
    fixture.detectChanges();
    await pop;
    expect(fixture.componentInstance.closes()).toBe(0);
    push.mockRestore();
  });

  it('§NF/usability/controls/000931: a step back without an open dialog closes nothing', async () => {
    const fixture = setup();
    window.history.pushState(null, '');
    const pop = popped();
    window.history.back();
    await pop;
    expect(fixture.componentInstance.closes()).toBe(0);
  });

  it('§NF/usability/controls/000931: a page that went stops listening', async () => {
    const fixture = setup();
    fixture.componentInstance.open.set(true);
    fixture.detectChanges();
    fixture.destroy();
    const pop = popped();
    window.history.back();
    await pop;
    expect(fixture.componentInstance.closes()).toBe(0);
  });
});
