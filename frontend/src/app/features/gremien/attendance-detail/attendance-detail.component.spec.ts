import { Component, viewChild } from '@angular/core';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { GremienApiService } from '@core/api/gremien.service';
import { MEDIA } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { gremienApiMock, memberAttendance } from '../../../../testing/gremien-fixtures';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
import { AttendanceDetailComponent, type AttendanceDetailRequest } from './attendance-detail.component';
import { loadErrorToast, retryLoadError } from '../../../../testing/load-error';

@Component({
  standalone: true,
  imports: [AttendanceDetailComponent],
  template: `
    <button type="button" class="anchor">Zelle</button>
    <button type="button" class="outside">Draußen</button>
    <app-attendance-detail gremiumId="g-1" (changed)="changed()" />
  `,
})
class Host {
  readonly changed = jest.fn();
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
  const client = { excuseLate: jest.fn(() => of([])) };
  const view = await render(Host, {
    providers: [
      { provide: GremienApiService, useValue: api },
      { provide: ApiClient, useValue: client },
    ],
  });
  const anchor = view.container.querySelector('.anchor') as HTMLButtonElement;
  const cmp = view.fixture.componentInstance.detail();
  const openWith = async (request: AttendanceDetailRequest, target: EventTarget | null = anchor) => {
    cmp.open(request, target);
    view.fixture.detectChanges();
    await view.fixture.whenStable();
    view.fixture.detectChanges();
  };
  return { ...view, api, client, anchor, cmp, openWith, restore };
}

describe('AttendanceDetailComponent', () => {
  let restore: (() => void) | null = null;
  afterEach(() => {
    restore?.();
    restore = null;
    localStorage.clear();
  });

  /** With one month there is no month heading. */
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
    expect(dialog.querySelector('.gad__month')).toBeNull();
    expect(dialog.classList.contains('gad--placed')).toBe(true);
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  /** § 001311 */
  it('poolSeats: shows the pool seats of a pool substitute with the represented member', async () => {
    const seats = memberAttendance({
      principalId: 'p-7',
      displayName: 'Lea Pool',
      meetings: [
        { meetingId: 'm-2', title: '32. Sitzung', date: '2026-09-29', startTime: '18:00:00', status: 'seat', delegateName: 'Anna Berg' },
        { meetingId: 'm-3', title: '31. Sitzung', date: '2026-09-15', startTime: '18:00:00', status: 'no_seat', delegateName: null },
      ],
    });
    const view = await setup({ api: gremienApiMock({ memberAttendance: jest.fn(() => of(seats)) }) });
    restore = view.restore;
    await view.openWith({ ...ONE, principalId: 'p-7', name: 'Lea Pool', heading: 'Lea Pool · September 2026', pool: true });
    expect(view.api.memberAttendance).toHaveBeenCalledWith('g-1', 'p-7', '2026-09', true);
    const dialog = screen.getByRole('dialog', { name: 'Lea Pool · September 2026' });
    expect(dialog).toHaveTextContent('Vertreten');
    expect(dialog).toHaveTextContent('für Anna Berg');
    expect(dialog).toHaveTextContent('Kein Sitz');
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  /** § 000922 */
  it('excuses an own absence later and tells the matrix to read again', async () => {
    const late = memberAttendance({
      meetings: [
        { meetingId: 'm-2', title: '32. Sitzung', date: '2026-09-29', startTime: '18:00:00', status: 'absent', delegateName: null, lateExcuseUntil: '2099-01-01T00:00:00Z' },
        { meetingId: 'm-3', title: '31. Sitzung', date: '2026-09-15', startTime: '18:00:00', status: 'absent', delegateName: null },
      ],
    });
    const view = await setup({ api: gremienApiMock({ memberAttendance: jest.fn(() => of(late)) }) });
    restore = view.restore;
    await view.openWith(ONE);
    const buttons = screen.getAllByRole('button', { name: 'Nachträglich entschuldigen' });
    expect(buttons).toHaveLength(1);
    await userEvent.click(buttons[0]);
    view.fixture.detectChanges();
    expect(screen.queryByRole('dialog', { name: 'Finn Schulze · September 2026' })).toBeNull();
    const dialog = screen.getByRole('dialog', { name: 'Nachträglich entschuldigen' });
    await userEvent.type(within(dialog).getByLabelText(/Grund/), 'Krank');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Entschuldigen' }));
    view.fixture.detectChanges();
    expect(view.client.excuseLate).toHaveBeenCalledWith('m-2', 'Krank');
    expect(view.fixture.componentInstance.changed).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog', { name: 'Nachträglich entschuldigen' })).toBeNull();
  });

  it('closes the late excuse on "Abbrechen" without a change', async () => {
    const view = await setup();
    restore = view.restore;
    view.cmp.askExcuse(memberAttendance().meetings[0]);
    view.fixture.detectChanges();
    await userEvent.click(within(screen.getByRole('dialog', { name: 'Nachträglich entschuldigen' })).getByRole('button', { name: 'Abbrechen' }));
    view.fixture.detectChanges();
    expect(screen.queryByRole('dialog', { name: 'Nachträglich entschuldigen' })).toBeNull();
    expect(view.fixture.componentInstance.changed).not.toHaveBeenCalled();
  });

  /** A close before the next frame leaves the focus where the close put it. */
  it('takes the focus on the frame after the open (spec 000513)', async () => {
    const view = await setup();
    restore = view.restore;
    await view.openWith(ONE);
    await new Promise((resolve) => requestAnimationFrame(resolve));
    expect(screen.getByRole('dialog')).toHaveFocus();
    view.cmp.close();
    view.fixture.detectChanges();
    view.anchor.focus();
    await view.openWith(ONE);
    view.cmp.close();
    view.fixture.detectChanges();
    await new Promise((resolve) => requestAnimationFrame(resolve));
    expect(view.anchor).toHaveFocus();
  });

  /** A second close does nothing. */
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
    view.cmp.close();
    expect(view.cmp.isOpen()).toBe(false);
  });

  /** When closed, the listeners do nothing. */
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
    const memberAttendanceFn = jest.fn((): ReturnType<GremienApiService['memberAttendance']> => throwError(() => new Error('x')));
    const view = await setup({ api: gremienApiMock({ memberAttendance: memberAttendanceFn }) });
    restore = view.restore;
    await view.openWith(ONE);
    expect(loadErrorToast()).toContain('Die Sitzungen konnten nicht geladen werden.');
    memberAttendanceFn.mockReturnValue(of(memberAttendance()));
    retryLoadError();
    view.fixture.detectChanges();
    expect(loadErrorToast()).toBeNull();
    view.cmp.close(false);
    view.cmp.retry();
    expect(memberAttendanceFn).toHaveBeenCalledTimes(2);
  });

  /** A second request with the same element stays in the top layer. */
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
