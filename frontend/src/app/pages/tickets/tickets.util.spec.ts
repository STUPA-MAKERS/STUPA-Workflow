import type { TicketArea, TicketEvent, TicketMail } from '@core/api/tickets.service';
import { de, type Translate } from '@core/i18n/translations';
import {
  areaOf,
  categoryName,
  eventText,
  isOpen,
  mailSourceScan,
  reporterName,
  reporterRowName,
  ticketAge,
  ticketIcon,
  addressesValid,
  parseAddresses,
  recipientsText,
  reporterEventText,
  sentLine,
  skippedLine,
  withSkipped,
} from './tickets.util';
import { personName } from '@shared/person-label.util';

/** The German texts with their parameters filled in; `{shortName}` as I18nService fills it. */
const t: Translate = (key, params = {}) =>
  Object.entries({ shortName: 'STUPA', ...params }).reduce(
    (text, [k, v]) => text.replace(`{${k}}`, String(v)),
    de[key] as string,
  );

const MARA = { principalId: 'p1', displayName: 'Mara Keller' };
const JONAS = { principalId: 'p2', displayName: 'Jonas Albrecht' };

function ev(over: Partial<TicketEvent>): TicketEvent {
  return { id: 'e1', kind: 'created', actor: MARA, at: '2026-10-15T08:12:00Z', payload: {}, ...over };
}

describe('tickets.util', () => {
  it('knows the open states', () => {
    expect(isOpen('new')).toBe(true);
    expect(isOpen('in_progress')).toBe(true);
    expect(isOpen('waiting')).toBe(true);
    expect(isOpen('done')).toBe(false);
    expect(isOpen('rejected')).toBe(false);
  });

  it('names a person, and a deleted one', () => {
    expect(personName(MARA, t)).toBe('Mara Keller');
    expect(personName({ principalId: null, displayName: null }, t)).toBe('Gelöschte Person');
    expect(personName(null, t)).toBe('Gelöschte Person');
  });

  it('names the reporter by name, else e-mail, else anonymized', () => {
    const base = { principalId: null, displayName: null, email: null, anonymized: false };
    expect(reporterName({ ...base, displayName: 'Lea' }, t)).toBe('Lea');
    expect(reporterName({ ...base, email: 'kasse@example.org' }, t)).toBe('kasse@example.org');
    expect(reporterName(base, t)).toBe('Gelöschte Person');
    expect(reporterName({ ...base, displayName: 'Lea', anonymized: true }, t)).toBe('Anonymisiert');
  });

  it('names the reporter of a list row, but never by the e-mail', () => {
    const base = { principalId: null, displayName: null, email: null, anonymized: false };
    expect(reporterRowName({ ...base, displayName: 'Lea', email: 'lea@example.org' }, t)).toBe('Lea');
    expect(reporterRowName({ ...base, email: 'kasse@example.org' }, t)).toBeNull();
    expect(reporterRowName(base, t)).toBe('Gelöschte Person');
    expect(reporterRowName({ ...base, displayName: 'Lea', anonymized: true }, t)).toBe('Anonymisiert');
  });

  describe('ticketAge', () => {
    const now = new Date(2026, 9, 15, 18, 0);
    const at = (d: Date) => d.toISOString();
    it.each([
      [new Date(2026, 9, 15, 17, 59, 30), 'gerade eben'],
      [new Date(2026, 9, 15, 17, 48), 'vor 12 Min.'],
      [new Date(2026, 9, 15, 15, 0), 'vor 3 Std.'],
      [new Date(2026, 9, 14, 21, 14), 'gestern'],
      [new Date(2026, 9, 12, 9, 0), '12.10.'],
      [new Date(2025, 11, 30, 9, 0), '30.12.2025'],
    ])('writes %s as %s', (then, text) => {
      expect(ticketAge(at(then), now, 'de-DE', t)).toBe(text);
    });

    it('gives nothing for a bad date', () => {
      expect(ticketAge('nope', now, 'de-DE', t)).toBe('');
    });
  });

  describe('eventText', () => {
    it('writes the creation, with and without the confirmation', () => {
      expect(eventText(ev({ payload: { confirmationSent: true } }), 'Tobias Brandt', t)).toBe(
        'Eingangsbestätigung an Tobias Brandt gesendet',
      );
      expect(eventText(ev({ actor: null }), 'Tobias', t)).toBe('Ticket gemeldet');
    });

    it('writes a state change, a duplicate and an unknown state', () => {
      expect(eventText(ev({ kind: 'status', payload: { from: 'new', to: 'in_progress' } }), '', t)).toBe(
        'Mara Keller: Status Neu → In Bearbeitung',
      );
      expect(eventText(ev({ kind: 'status', payload: { from: 'x' as never, to: null } }), '', t)).toBe(
        'Mara Keller: Status Neu → Neu',
      );
      expect(
        eventText(ev({ kind: 'status', payload: { from: 'new', to: 'rejected', duplicateOf: 'T-0012' } }), '', t),
      ).toBe('Mara Keller hat das Ticket als Duplikat von T-0012 geschlossen');
    });

    /**
     * When the system assigns, the text is never "übernommen". A deleted person can be on both
     * sides.
     */
    it('writes the assignee changes', () => {
      expect(eventText(ev({ kind: 'assignee', payload: { to: null } }), '', t)).toBe(
        'Mara Keller hat die Zuweisung entfernt',
      );
      expect(eventText(ev({ kind: 'assignee', payload: {} }), '', t)).toBe('Mara Keller hat die Zuweisung entfernt');
      expect(eventText(ev({ kind: 'assignee', payload: { to: MARA } }), '', t)).toBe(
        'Mara Keller hat das Ticket übernommen',
      );
      expect(eventText(ev({ kind: 'assignee', payload: { to: JONAS } }), '', t)).toBe(
        'Mara Keller hat das Ticket Jonas Albrecht zugewiesen',
      );
      expect(eventText(ev({ kind: 'assignee', actor: null, payload: { to: MARA } }), '', t)).toBe(
        'STUPA hat das Ticket Mara Keller zugewiesen',
      );
      const gone = { principalId: null, displayName: null };
      expect(eventText(ev({ kind: 'assignee', actor: gone, payload: { to: gone } }), '', t)).toBe(
        'Gelöschte Person hat das Ticket Gelöschte Person zugewiesen',
      );
    });

    it('writes a kind change and an unknown kind', () => {
      expect(eventText(ev({ kind: 'kind', payload: { from: 'bug', to: 'idea' } }), '', t)).toBe(
        'Mara Keller: Kategorie Fehler → Idee',
      );
      expect(eventText(ev({ kind: 'kind', payload: {} }), '', t)).toBe('Mara Keller: Kategorie Fehler → Fehler');
    });

    it('writes a change of the Kategorie of a Bereich by the names', () => {
      expect(
        eventText(ev({ kind: 'category', payload: { from: 'Raumanfrage', to: 'Schlüssel' } }), '', t),
      ).toBe('Mara Keller: Kategorie Raumanfrage → Schlüssel');
      expect(eventText(ev({ kind: 'category', payload: { from: null, to: 'Schlüssel' } }), '', t)).toBe(
        'Mara Keller: Kategorie Keine → Schlüssel',
      );
      expect(eventText(ev({ kind: 'category', payload: { from: 'Schlüssel' } }), '', t)).toBe(
        'Mara Keller: Kategorie Schlüssel → Keine',
      );
    });

    it('writes a move with both names, also after a Bereich is gone', () => {
      const payload = { from: 'a1', to: 'a2', fromName: 'Plattform', toName: 'AStA-Büro' };
      expect(eventText(ev({ kind: 'area', payload }), '', t)).toBe(
        'Mara Keller hat das Ticket von Plattform nach AStA-Büro verschoben',
      );
      expect(eventText(ev({ kind: 'area', payload: { from: 'a1', to: 'a2' } }), '', t)).toBe(
        'Mara Keller hat das Ticket von einem gelöschten Bereich nach einem gelöschten Bereich verschoben',
      );
    });

    it('writes a done to-do, and one the viewer may not read', () => {
      expect(eventText(ev({ kind: 'todo_done', payload: { cardTitle: 'PDF-Kopf' } }), '', t)).toBe(
        'Mara Keller hat das To-Do „PDF-Kopf“ erledigt',
      );
      expect(eventText(ev({ kind: 'todo_done', payload: { cardTitle: null } }), '', t)).toBe(
        'Mara Keller hat ein To-Do erledigt',
      );
    });
  });

  describe('Bereich and Kategorie', () => {
    const ASTA: TicketArea = {
      id: 'a-asta',
      name: 'AStA-Büro',
      gremiumId: 'g1',
      platform: false,
      notifyNew: true,
      inApp: false,
      categories: [{ id: 'c1', name: 'Raumanfrage' }],
      mine: true,
    };

    it('gives a ticket the icon of its kind, else the ticket', () => {
      expect(ticketIcon('bug')).toBe('bug');
      expect(ticketIcon(null)).toBe('ticket');
    });

    it('finds the Bereich of a ticket', () => {
      expect(areaOf('a-asta', [ASTA])).toBe(ASTA);
      expect(areaOf('x', [ASTA])).toBeNull();
    });

    it('names the kind, else the Kategorie of the Bereich, else nothing', () => {
      expect(categoryName({ kind: 'idea', categoryId: null, areaId: 'x' }, [], t)).toBe('Idee');
      expect(categoryName({ kind: null, categoryId: 'c1', areaId: 'a-asta' }, [ASTA], t)).toBe('Raumanfrage');
      expect(categoryName({ kind: null, categoryId: null, areaId: 'a-asta' }, [ASTA], t)).toBe('');
      expect(categoryName({ kind: null, categoryId: 'c1', areaId: 'gone' }, [ASTA], t)).toBe('');
    });
  });

  describe('the mails of a ticket', () => {
    const mail = (over: Partial<TicketMail> = {}): TicketMail => ({
      id: 'm1',
      noteId: null,
      direction: 'in',
      fromName: 'Anna Beispiel',
      fromAddress: 'anna@example.org',
      cc: [],
      subject: 'Raumanfrage',
      automatic: false,
      source: 'clean',
      sourceSize: 2048,
      skipped: [],
      at: '2026-11-23T10:00:00Z',
      ...over,
    });

    it('names an automatic mail with its sender and its subject', () => {
      const event = ev({ kind: 'mail_auto', actor: null, payload: { from: 'Anna Beispiel', subject: 'Abwesend' } });
      expect(eventText(event, 'Tobias', t)).toBe('Automatische Antwort von Anna Beispiel: Abwesend');
      expect(eventText(ev({ kind: 'mail_auto', actor: null, payload: {} }), 'Tobias', t)).toBe(
        'Automatische Antwort von Tobias: ',
      );
    });

    it('maps the state of a source to the scan state of a file', () => {
      expect(mailSourceScan(mail())).toBe('clean');
      expect(mailSourceScan(mail({ source: 'infected' }))).toBe('quarantined');
      expect(mailSourceScan(mail({ source: 'closed' }))).toBe('scanning');
      expect(mailSourceScan(mail({ source: 'gone' }))).toBeNull();
    });

    it('names each left-out file with its size and the cause', () => {
      const skipped = [
        { name: 'plan.pdf', size: 12 * 1024 * 1024, reason: 'size' as const },
        { name: 'daten.zip', size: 2048, reason: 'type' as const },
      ];
      expect(skippedLine(mail({ skipped }), 'de-DE', t)).toBe(
        'Nicht übernommen: plan.pdf (12 MB, zu groß), daten.zip (2 KB, Dateityp nicht erlaubt)',
      );
      expect(skippedLine(mail(), 'de-DE', t)).toBe('');
      expect(skippedLine(undefined, 'de-DE', t)).toBe('');
    });

    it('names the state and the recipients of a sent mail', () => {
      const out = mail({ direction: 'out', to: ['anna@example.org'], cc: ['ben@example.org'], state: 'sent' });
      expect(sentLine(out, t)).toBe('Gesendet an anna@example.org (Cc: ben@example.org)');
      expect(sentLine({ ...out, cc: [], state: 'sending' }, t)).toBe('Mail an anna@example.org');
      expect(sentLine({ ...out, cc: [], state: 'failed' }, t)).toBe('Mail an anna@example.org');
      expect(sentLine(mail(), t)).toBe('');
      expect(sentLine(undefined, t)).toBe('');
      expect(recipientsText(['a@x.org', 'b@x.org'], [], t)).toBe('a@x.org, b@x.org');
    });

    it('names a sent mail without stored recipients, and a status change with an unknown status', () => {
      const out = mail({ direction: 'out', cc: [], state: 'sent' });
      expect(sentLine({ ...out, to: undefined }, t)).toBe('Gesendet an ');
      expect(reporterEventText({ from: 'new', to: 'done' }, t)).toBe(
        reporterEventText({ from: 'unknown', to: 'done' }, t),
      );
      expect(reporterEventText({ from: 'new', to: 'unknown' }, t)).toBe(reporterEventText({ from: 'new', to: 'new' }, t));
    });

    it('reads the addresses that a person typed', () => {
      expect(parseAddresses(' Anna@Example.org, ben@example.org;anna@example.org  carla@example.org ')).toEqual([
        'anna@example.org',
        'ben@example.org',
        'carla@example.org',
      ]);
      expect(parseAddresses('  ')).toEqual([]);
      expect(addressesValid(['anna@example.org'])).toBe(true);
      expect(addressesValid(['anna@example.org', 'kein'])).toBe(false);
    });

    it('puts the line under the text of the message', () => {
      expect(withSkipped('Hallo', 'Zeile')).toBe('Hallo\n\nZeile');
      expect(withSkipped('', 'Zeile')).toBe('Zeile');
      expect(withSkipped('Hallo', '')).toBe('Hallo');
    });
  });
});
