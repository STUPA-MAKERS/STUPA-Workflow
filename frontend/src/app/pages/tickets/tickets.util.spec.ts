import type { TicketEvent } from '@core/api/tickets.service';
import { de, type Translate } from '@core/i18n/translations';
import {
  eventText,
  isOpen,
  reporterName,
  reporterRowName,
  ticketAge,
} from './tickets.util';
import { personName } from '@shared/person-label.util';

/** The German texts with their parameters filled in. */
const t: Translate = (key, params = {}) =>
  Object.entries(params).reduce((text, [k, v]) => text.replace(`{${k}}`, String(v)), de[key] as string);

const MARA = { principalId: 'p1', displayName: 'Mara Keller' };
const JONAS = { principalId: 'p2', displayName: 'Jonas Albrecht' };

function ev(over: Partial<TicketEvent>): TicketEvent {
  return { id: 'e1', kind: 'created', actor: MARA, at: '2026-10-15T08:12:00Z', payload: {}, ...over };
}

describe('tickets.util', () => {
  it('knows the open states', () => {
    expect(isOpen('new')).toBe(true);
    expect(isOpen('in_progress')).toBe(true);
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
        'Mara Keller: Art Fehler → Idee',
      );
      expect(eventText(ev({ kind: 'kind', payload: {} }), '', t)).toBe('Mara Keller: Art Fehler → Fehler');
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
});
