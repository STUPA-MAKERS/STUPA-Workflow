import { TestBed } from '@angular/core/testing';
import { render, screen, within } from '@testing-library/angular';
import { I18nService } from '@core/i18n/i18n.service';
import { runAxe } from '../../../../testing/a11y';
import { HistoryComponent, type HistoryEntry } from './history.component';

/** A local time, so the day grouping does not depend on the time zone of the runner. */
const at = (y: number, m: number, d: number, h: number, min: number) =>
  new Date(y, m - 1, d, h, min).toISOString();

const YEAR = new Date().getFullYear();

const ENTRIES: HistoryEntry[] = [
  // Given out of order on purpose.
  { at: at(YEAR, 9, 26, 14, 12), icon: 'send', title: 'Eingereicht', kind: 'neutral', actor: 'Du' },
  {
    at: at(YEAR, 9, 28, 9, 40),
    icon: 'flow',
    title: 'In Prüfung',
    kind: 'warn',
    actor: 'Studierendenparlament',
    body: 'Übergang „Prüfung beginnen“',
  },
  {
    at: at(YEAR, 9, 27, 21, 5),
    icon: 'edit',
    title: 'Version 2 gespeichert',
    actor: 'Du',
    body: 'Geändert: Kostenaufstellung',
  },
  {
    at: at(YEAR, 9, 28, 16, 20),
    icon: 'cal',
    title: 'Auf Tagesordnung',
    kind: 'accent',
    actor: 'Studierendenparlament',
  },
];

describe('HistoryComponent', () => {
  it('groups by day, newest day first and newest event first', async () => {
    await render(HistoryComponent, { inputs: { entries: ENTRIES } });
    const lists = screen.getAllByRole('list');
    expect(lists).toHaveLength(3);
    expect(lists[0]).toHaveAccessibleName(
      new Date(YEAR, 8, 28).toLocaleDateString('de-DE', {
        weekday: 'long',
        day: 'numeric',
        month: 'long',
      }),
    );
    expect(lists[0]).toHaveAccessibleName(/^Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag/);
    const titles = lists.map((l) =>
      within(l)
        .getAllByRole('listitem')
        .map((li) => li.querySelector('.hist__title')?.textContent?.trim()),
    );
    expect(titles).toEqual([
      ['Auf Tagesordnung', 'In Prüfung'],
      ['Version 2 gespeichert'],
      ['Eingereicht'],
    ]);
  });

  it('colours a status title and leaves an event in the text colour', async () => {
    const { container } = await render(HistoryComponent, { inputs: { entries: ENTRIES } });
    const status = container.querySelectorAll('app-status-text');
    expect(Array.from(status).map((s) => s.className)).toEqual([
      'st st--accent',
      'st st--warn',
      'st st--neutral',
    ]);
    const version = screen.getByText('Version 2 gespeichert');
    expect(version.closest('app-status-text')).toBeNull();
  });

  it('shows the body and a meta line with the actor and the time', async () => {
    await render(HistoryComponent, { inputs: { entries: ENTRIES } });
    expect(screen.getByText('Übergang „Prüfung beginnen“')).toBeInTheDocument();
    const meta = screen.getByText('Studierendenparlament · 09:40');
    expect(meta.tagName).toBe('TIME');
    expect(meta).toHaveAttribute('datetime', ENTRIES[1].at);
  });

  it('shows only the time when there is no actor', async () => {
    await render(HistoryComponent, {
      inputs: { entries: [{ at: at(YEAR, 3, 2, 8, 5), icon: 'send', title: 'Eingereicht' }] },
    });
    expect(screen.getByText('08:05')).toBeInTheDocument();
  });

  it('adds the year to a day of another year', async () => {
    await render(HistoryComponent, {
      inputs: { entries: [{ at: at(2024, 3, 2, 8, 5), icon: 'send', title: 'Eingereicht' }] },
    });
    expect(screen.getByRole('list')).toHaveAccessibleName(/2024/);
  });

  it('follows the locale', async () => {
    const view = await render(HistoryComponent, {
      inputs: { entries: [{ at: at(YEAR, 9, 28, 16, 20), icon: 'cal', title: 'Auf Tagesordnung' }] },
    });
    expect(screen.getByRole('list')).toHaveAccessibleName(/September/);
    expect(screen.getByRole('list')).not.toHaveAccessibleName(/^[A-Z][a-z]+day/);
    const i18n = TestBed.inject(I18nService);
    i18n.setLocale('en');
    view.fixture.detectChanges();
    expect(screen.getByRole('list')).toHaveAccessibleName(/^[A-Z][a-z]+day/);
    i18n.setLocale('de');
  });

  it('switches the row surface', async () => {
    const { container } = await render(HistoryComponent, {
      inputs: { entries: ENTRIES, surface: 3 },
    });
    expect(container.querySelector('ol')).toHaveClass('rowgroup', 'rowgroup--bg3');
    expect(container.querySelector('ol')).not.toHaveClass('rowgroup--bg1');
  });

  it('puts the entries with an invalid date into a last group and does not throw', async () => {
    await render(HistoryComponent, {
      inputs: {
        entries: [
          { at: 'kein Datum', icon: 'edit', title: 'Kaputt', actor: 'Du' },
          { at: at(YEAR, 9, 28, 16, 20), icon: 'cal', title: 'Auf Tagesordnung' },
          { at: null as unknown as string, icon: 'send', title: 'Ohne Zeit' },
        ],
      },
    });
    const lists = screen.getAllByRole('list');
    expect(lists).toHaveLength(2);
    expect(lists[1]).toHaveAccessibleName('Ohne Datum');
    expect(within(lists[1]).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      expect.stringContaining('Kaputt'),
      expect.stringContaining('Ohne Zeit'),
    ]);
    expect(within(lists[1]).getByText('Du').tagName).toBe('SPAN');
    expect(lists[1].querySelector('time')).toBeNull();
  });

  it('lists the changed fields of an event with the old and the new value', async () => {
    const { container } = await render(HistoryComponent, {
      inputs: {
        entries: [
          {
            at: at(YEAR, 9, 27, 21, 5),
            icon: 'edit',
            title: 'Version 2',
            body: 'Zeile 1\nZeile 2',
            changes: [
              { kind: 'warn', tag: 'Geändert', label: 'Teilnehmende', old: '300', new: '350' },
              { kind: 'warn', tag: 'Geändert', label: 'Kostenaufstellung' },
              { kind: 'accent', tag: 'Hinzugefügt', label: 'Raum', new: 'R 101' },
              { kind: 'error', tag: 'Entfernt', label: 'Notiz', old: 'alt' },
            ],
          },
        ],
      },
    });
    const items = [...container.querySelectorAll('.hist__changes li')];
    expect(items).toHaveLength(4);
    expect(items[0].querySelector('app-status-text')).toHaveClass('st--warn');
    expect(items[0].querySelector('del')?.textContent).toBe('300');
    expect(items[0].querySelector('ins')?.textContent).toBe('350');
    expect(items[0].querySelector('.hist__arrow')).not.toBeNull();
    // A field without a short value shows only its name.
    expect(items[1].querySelector('del, ins')).toBeNull();
    expect(items[1].textContent).not.toContain(':');
    expect(items[2].querySelector('del')).toBeNull();
    expect(items[2].querySelector('.hist__arrow')).toBeNull();
    expect(items[3].querySelector('ins')).toBeNull();
    expect(items[3].querySelector('app-status-text')).toHaveClass('st--error');
    expect(container.querySelector('.hist__body')?.textContent).toBe('Zeile 1\nZeile 2');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('draws nothing for no entries', async () => {
    await render(HistoryComponent, { inputs: { entries: [] } });
    expect(screen.queryByRole('list')).toBeNull();
  });

  it('has no a11y violations', async () => {
    const { container } = await render(HistoryComponent, { inputs: { entries: ENTRIES } });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
