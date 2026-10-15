import { Component, viewChild } from '@angular/core';
import { fireEvent, render, screen } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { GremienApiService } from '@core/api/gremien.service';
import { MEDIA } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { gremienApiMock, memberAttendance } from '../../../../testing/gremien-fixtures';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
import { AttendanceDetailComponent, type AttendanceDetailRequest } from './attendance-detail.component';

@Component({
  standalone: true,
  imports: [AttendanceDetailComponent],
  template: `
    <button type="button" class="anchor">Zelle</button>
    <button type="button" class="outside">Draußen</button>
    <app-attendance-detail gremiumId="g-1" />
  `,
})
class Host {
  readonly detail = viewChild.required(AttendanceDetailComponent);
}

const ONE: AttendanceDetailRequest = {
  principalId: 'p-1',
  name: 'Finn Schulze',
  heading: 'Finn Schulze · September 2026',
  summary: '0 von 2 Sitzungen anwesend, 1 entschuldigt',
  months: ['2026-09'],
};

async function setup(opts: { api?: ReturnType<typeof gremienApiMock>; phone?: boolean } = {}) {
  localStorage.setItem('ap.locale', 'de');
  const restore = matchMediaQueries(...(opts.phone ? [MEDIA.phone] : []));
  const api = opts.api ?? gremienApiMock();
  const view = await render(Host, { providers: [{ provide: GremienApiService, useValue: api }] });
  const anchor = view.container.querySelector('.anchor') as HTMLButtonElement;
  const cmp = view.fixture.componentInstance.detail();
  const openWith = async (request: AttendanceDetailRequest, target: EventTarget | null = anchor) => {
    cmp.open(request, target);
    view.fixture.detectChanges();
    await view.fixture.whenStable();
    view.fixture.detectChanges();
  };
  return { ...view, api, anchor, cmp, openWith, restore };
}

describe('AttendanceDetailComponent', () => {
  let restore: (() => void) | null = null;
  afterEach(() => {
    restore?.();
    restore = null;
    localStorage.clear();
  });

  it('shows the meetings of one month under the cell, with the state and the delegate', async () => {
    const view = await setup();
    restore = view.restore;
    await view.openWith(ONE);
    expect(view.api.memberAttendance).toHaveBeenCalledWith('g-1', 'p-1', '2026-09');
    const dialog = screen.getByRole('dialog', { name: 'Finn Schulze · September 2026' });
    expect(dialog).toHaveTextContent('0 von 2 Sitzungen anwesend, 1 entschuldigt');
    expect(dialog).toHaveTextContent('32. Sitzung');
    expect(dialog).toHaveTextContent('Entschuldigt');
    expect(dialog).toHaveTextContent('Stimme übertragen');
    expect(dialog).toHaveTextContent('an Kai Meier');
    expect(dialog).toHaveTextContent('29.09.');
    // One month: no month heading.
    expect(dialog.querySelector('.gad__month')).toBeNull();
    expect(dialog.classList.contains('gad--placed')).toBe(true);
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('closes on Escape and gives the focus back to the cell', async () => {
    const view = await setup();
    restore = view.restore;
    await view.openWith(ONE);
    const dialog = screen.getByRole('dialog');
    fireEvent.keyDown(dialog, { key: 'Tab' });
    expect(view.cmp.isOpen()).toBe(true);
    fireEvent.keyDown(dialog, { key: 'Escape' });
    view.fixture.detectChanges();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(view.anchor);
    // A second close does nothing.
    view.cmp.close();
    expect(view.cmp.isOpen()).toBe(false);
  });

  it('closes on a pointer down outside, not on the cell or inside', async () => {
    const view = await setup();
    restore = view.restore;
    await view.openWith(ONE);
    fireEvent.pointerDown(view.anchor);
    fireEvent.pointerDown(screen.getByRole('dialog'));
    expect(view.cmp.isOpen()).toBe(true);
    window.dispatchEvent(new Event('resize'));
    window.dispatchEvent(new Event('scroll'));
    fireEvent.pointerDown(view.container.querySelector('.outside') as HTMLElement);
    view.fixture.detectChanges();
    expect(view.cmp.isOpen()).toBe(false);
    // Closed: the listeners do nothing.
    fireEvent.pointerDown(document.body);
    window.dispatchEvent(new Event('resize'));
    expect(view.cmp.isOpen()).toBe(false);
  });

  it('groups several months with a heading and opens above the cell without room below', async () => {
    const api = gremienApiMock({
      memberAttendance: jest.fn((_g: string, _p: string, month: string) =>
        of(memberAttendance({ month, meetings: month === '2026-08' ? [] : memberAttendance().meetings })),
      ),
    });
    const view = await setup({ api });
    restore = view.restore;
    view.anchor.getBoundingClientRect = () => ({ top: 700, bottom: 740, left: 900, right: 980, width: 80, height: 40, x: 900, y: 700, toJSON: () => ({}) });
    const proto = HTMLElement.prototype.getBoundingClientRect;
    HTMLElement.prototype.getBoundingClientRect = function () {
      return this.classList.contains('gad--pop')
        ? ({ top: 0, bottom: 300, left: 0, right: 300, width: 300, height: 300, x: 0, y: 0, toJSON: () => ({}) } as DOMRect)
        : proto.call(this);
    };
    try {
      await view.openWith({ ...ONE, heading: 'Finn Schulze', months: ['2026-09', '2026-08'] });
      const dialog = screen.getByRole('dialog');
      expect([...dialog.querySelectorAll('.gad__month')].map((h) => h.textContent)).toEqual(['September 2026']);
      expect(dialog.style.top).toBe(`${700 - 6 - 300}px`);
    } finally {
      HTMLElement.prototype.getBoundingClientRect = proto;
    }
  });

  it('says when the months hold no meeting, and reads nothing without a month', async () => {
    const api = gremienApiMock({ memberAttendance: jest.fn(() => of(memberAttendance({ meetings: [] }))) });
    const view = await setup({ api });
    restore = view.restore;
    view.cmp.open(ONE);
    view.fixture.detectChanges();
    expect(screen.getByText('Keine Sitzung in diesem Zeitraum.')).toBeTruthy();
    await view.openWith({ ...ONE, months: [] });
    expect(api.memberAttendance).toHaveBeenCalledTimes(1);
    expect(view.cmp.loading()).toBe(false);
  });

  it('reports a failed read and reads again', async () => {
    const memberAttendanceFn = jest.fn(() => throwError(() => new Error('x')));
    const view = await setup({ api: gremienApiMock({ memberAttendance: memberAttendanceFn }) });
    restore = view.restore;
    await view.openWith(ONE);
    expect(screen.getByRole('alert')).toHaveTextContent('Die Sitzungen konnten nicht geladen werden.');
    memberAttendanceFn.mockReturnValue(of(memberAttendance()));
    screen.getByRole('button', { name: 'Erneut versuchen' }).click();
    view.fixture.detectChanges();
    expect(screen.queryByRole('alert')).toBeNull();
    view.cmp.close(false);
    view.cmp.retry();
    expect(memberAttendanceFn).toHaveBeenCalledTimes(2);
  });

  it('puts the popover into the top layer once', async () => {
    const show = jest.fn(function (this: HTMLElement) {
      this.setAttribute('data-open', '');
    });
    const matches = HTMLElement.prototype.matches;
    Object.defineProperty(HTMLElement.prototype, 'showPopover', { configurable: true, value: show });
    HTMLElement.prototype.matches = function (sel: string) {
      if (sel === ':popover-open') return this.hasAttribute('data-open');
      return matches.call(this, sel);
    };
    try {
      const view = await setup();
      restore = view.restore;
      await view.openWith(ONE);
      expect(show).toHaveBeenCalledTimes(1);
      // A second request with the same element stays in the top layer.
      await view.openWith({ ...ONE, months: ['2026-08'] });
      expect(show).toHaveBeenCalledTimes(1);
    } finally {
      delete (HTMLElement.prototype as { showPopover?: unknown }).showPopover;
      HTMLElement.prototype.matches = matches;
    }
  });

  it('survives an engine without the :popover-open selector', async () => {
    const show = jest.fn();
    const matches = HTMLElement.prototype.matches;
    Object.defineProperty(HTMLElement.prototype, 'showPopover', { configurable: true, value: show });
    HTMLElement.prototype.matches = function (sel: string) {
      if (sel === ':popover-open') throw new SyntaxError('unknown');
      return matches.call(this, sel);
    };
    try {
      const view = await setup();
      restore = view.restore;
      await view.openWith(ONE);
      expect(show).toHaveBeenCalledTimes(1);
    } finally {
      delete (HTMLElement.prototype as { showPopover?: unknown }).showPopover;
      HTMLElement.prototype.matches = matches;
    }
  });

  it('shows a bottom sheet on a phone that closes with the sheet', async () => {
    const view = await setup({ phone: true });
    restore = view.restore;
    await view.openWith({ ...ONE, heading: 'Finn Schulze', months: ['2026-09', '2026-08'] });
    expect(screen.getByRole('dialog', { name: 'Finn Schulze' })).toHaveTextContent('September 2026');
    fireEvent.pointerDown(view.container.querySelector('.outside') as HTMLElement);
    expect(view.cmp.isOpen()).toBe(true);
    view.cmp.onSheetOpen(true);
    expect(view.cmp.isOpen()).toBe(true);
    view.cmp.onSheetOpen(false);
    view.fixture.detectChanges();
    expect(view.cmp.isOpen()).toBe(false);
  });
});
