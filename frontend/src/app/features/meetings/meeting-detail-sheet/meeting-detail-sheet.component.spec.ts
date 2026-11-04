import { provideRouter, Router } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Meeting } from '@core/api/models';
import { meeting } from '../../../../testing/meeting-fixtures';
import { runAxe } from '../../../../testing/a11y';
import { MeetingDetailSheetComponent } from './meeting-detail-sheet.component';

const LIVE = meeting({ startedAt: new Date(2026, 9, 15, 18, 4).toISOString() });

async function setup(over: { meeting?: Meeting; split?: boolean; phone?: boolean } = {}) {
  const on = { edit: jest.fn(), remove: jest.fn(), beamer: jest.fn() };
  const view = await render(MeetingDetailSheetComponent, {
    inputs: { meeting: over.meeting ?? LIVE, split: over.split ?? true, phone: over.phone ?? false },
    on,
    providers: [provideRouter([{ path: '**', children: [] }])],
  });
  const router = view.fixture.debugElement.injector.get(Router);
  return { ...view, on, router };
}

const openMenu = async (): Promise<HTMLElement> => {
  await userEvent.click(screen.getByRole('button', { name: /^Weitere Aktionen/ }));
  return screen.findByRole('menu');
};

describe('MeetingDetailSheetComponent', () => {
  /** The title opens the sheet on the line of the actions; no line stands above it. */
  it('shows the head of a live meeting: status, date, time and minute-taker', async () => {
    const { fixture } = await setup();
    expect(document.querySelector('app-sheet-bar .sheet-bar__title [appSheetBarTitle]')).not.toBeNull();
    expect(document.querySelector('.sheet-bar__kicker')).toBeNull();
    expect(screen.getByText('Do, 15.10.2026')).toHaveClass('ms__part');
    expect(screen.getByRole('heading', { level: 2, name: 'Konstituierende Sitzung' })).toBeInTheDocument();
    expect(screen.getByText('Live')).toHaveClass('st--accent');
    expect(screen.getByText('seit 18:04')).toBeInTheDocument();
    expect(screen.getByText('Protokoll: Pia Protokoll')).toBeInTheDocument();
    expect(fixture.nativeElement.querySelector('.ms')).toHaveClass('ms--split');
    expect(await runAxe(fixture.nativeElement)).toHaveNoViolations();
  });

  /** The sheet holds no summary of the agenda, the attendance or the protocol: only the way in. */
  it('opens the meeting from the one large tile and reads nothing else', async () => {
    const { router } = await setup();
    expect(screen.queryByRole('heading', { name: 'Tagesordnung' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Anwesenheit' })).toBeNull();
    const tile = screen.getByRole('link', { name: 'Details' });
    expect(tile).toHaveAttribute('href', '/meetings/m-1');
    await userEvent.click(tile);
    expect(router.url).toBe('/meetings/m-1');
  });

  it('edits beside the title; the menu projects and deletes', async () => {
    const { on } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Sitzung bearbeiten: Konstituierende Sitzung' }));
    expect(on.edit).toHaveBeenCalledWith(LIVE);
    let menu = await openMenu();
    expect(within(menu).queryByRole('menuitem', { name: 'Sitzung bearbeiten' })).toBeNull();
    await userEvent.click(within(menu).getByRole('menuitem', { name: 'Beamer-Ansicht' }));
    expect(on.beamer).toHaveBeenCalledWith(LIVE);
    menu = await openMenu();
    await userEvent.click(within(menu).getByRole('menuitem', { name: 'Sitzung löschen' }));
    expect(on.remove).toHaveBeenCalledWith(LIVE);
  });

  it('puts the edit into the menu on a phone', async () => {
    const { on } = await setup({ phone: true, split: false });
    expect(screen.queryByRole('button', { name: /^Sitzung bearbeiten/ })).toBeNull();
    await userEvent.click(within(await openMenu()).getByRole('menuitem', { name: 'Sitzung bearbeiten' }));
    expect(on.edit).toHaveBeenCalled();
  });

  it('offers no beamer for a closed meeting', async () => {
    await setup({ meeting: meeting({ status: 'closed' }), phone: true });
    const menu = await openMenu();
    expect(within(menu).getAllByRole('menuitem').map((i) => i.textContent?.trim())).toEqual([
      'Sitzung bearbeiten',
      'Sitzung löschen',
    ]);
  });

  it('offers no delete without canDelete', async () => {
    await setup({ meeting: meeting({ canDelete: false }), phone: true });
    expect(within(await openMenu()).queryByRole('menuitem', { name: 'Sitzung löschen' })).toBeNull();
  });

  it('warns about a planned meeting without a minute-taker', async () => {
    await setup({
      meeting: meeting({ status: 'planned', protokollantId: null, protokollantName: null, startTime: '18:00', endTime: '20:00' }),
    });
    expect(screen.getByText('Keine Protokollführung')).toHaveClass('ms__warn');
    expect(screen.getByText('18:00–20:00')).toBeInTheDocument();
  });

  it('offers no edit and no menu without the manage right', async () => {
    await setup({ meeting: { ...LIVE, canManage: false } });
    expect(screen.queryByRole('button', { name: /Weitere Aktionen/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /bearbeiten/ })).toBeNull();
    expect(screen.getByRole('link', { name: 'Details' })).toBeInTheDocument();
  });

  it('leaves out an empty meta part and the time of a meeting without one', async () => {
    const { fixture } = await setup({
      meeting: meeting({ status: 'planned', date: null, gremiumName: null, startTime: null, protocolId: null }),
    });
    expect(fixture.nativeElement.querySelectorAll('.ms__part')).toHaveLength(2);
  });
});
