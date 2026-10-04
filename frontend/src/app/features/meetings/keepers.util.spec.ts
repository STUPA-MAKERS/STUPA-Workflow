import { de } from '@core/i18n/translations';
import type { TranslationKey } from '@core/i18n/translations';
import type { KeeperPeriod } from '@core/api/models';
import { AGENDA, meeting } from '../../../testing/meeting-fixtures';
import { currentPosition, handoverPreview, keeperLine, keeperNames, meetingKeeperLine } from './keepers.util';

function t(key: TranslationKey, params: Record<string, string | number> = {}): string {
  const text = (de as Record<string, string>)[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, k: string) => String(params[k] ?? ''));
}

function period(over: Partial<KeeperPeriod>): KeeperPeriod {
  return {
    principalId: 'pr-1',
    name: 'Mara Keller',
    fromAt: '2026-09-29T16:04:00Z',
    toAt: null,
    fromAgendaItemId: null,
    toAgendaItemId: null,
    fromPosition: 1,
    toPosition: null,
    ...over,
  };
}

const MARA = period({ toAt: '2026-09-29T16:55:00Z', toPosition: 3 });
const LEA = period({ principalId: 'pr-2', name: 'Lea Hoffmann', fromAt: '2026-09-29T16:55:00Z', fromPosition: 3 });

describe('keeperLine', () => {
  it('names a single keeper without a span', () => {
    expect(keeperLine([period({})], t, 'de')).toBe('Mara Keller');
  });

  it('writes every period with its TOPs and the time of a running handover (Z3, O2)', () => {
    expect(keeperLine([MARA, LEA], t, 'de')).toMatch(
      /^Mara Keller \(TOP 1–3\), Lea Hoffmann \(ab TOP 3, \d\d:55\)$/,
    );
    const ended = { ...LEA, toAt: '2026-09-29T19:12:00Z', toPosition: 3 };
    expect(keeperLine([MARA, ended], t, 'de')).toBe('Mara Keller (TOP 1–3), Lea Hoffmann (TOP 3)');
  });

  it('uses the times for a period without TOP numbers and skips a planned period', () => {
    const plain = period({ fromPosition: null, toAt: '2026-09-29T16:55:00Z' });
    const next = period({ principalId: 'pr-2', name: null, fromAt: '2026-09-29T16:55:00Z', fromPosition: null });
    const planned = period({ principalId: 'pr-3', fromAt: null });
    expect(keeperLine([plain, next, planned], t, 'de')).toMatch(/^Mara Keller \(\d\d:04–\d\d:55\), — \(ab \d\d:55\)$/);
    expect(keeperLine([planned], t, 'de')).toBe('');
  });

  it('mixes a TOP number with a time when one end has no item', () => {
    const half = period({ toAt: '2026-09-29T16:55:00Z', toPosition: null });
    expect(keeperLine([half, LEA], t, 'de')).toMatch(/^Mara Keller \(TOP 1–\d\d:55\)/);
    const none = period({ fromAt: '2026-09-29T16:04:00Z', fromPosition: null, toAt: 'x', toPosition: null });
    expect(keeperLine([none, LEA], t, 'de')).toMatch(/^Mara Keller \(ab \d\d:04\)/);
  });
});

describe('keeperNames and meetingKeeperLine', () => {
  it('names every keeper once, else the minute-taker', () => {
    const back = period({ fromAt: '2026-09-29T18:00:00Z', fromPosition: 5 });
    expect(keeperNames(meeting({ keeperPeriods: [MARA, LEA, back] }))).toBe('Mara Keller, Lea Hoffmann');
    expect(keeperNames(meeting({ keeperPeriods: [] }))).toBe('Pia Protokoll');
    expect(keeperNames(meeting({ keeperPeriods: [], protokollantName: null }))).toBe('');
    expect(meetingKeeperLine(meeting({ keeperPeriods: [] }), t, 'de')).toBe('Pia Protokoll');
    expect(meetingKeeperLine(meeting({ keeperPeriods: [], protokollantName: null }), t, 'de')).toBe('');
  });
});

describe('handoverPreview', () => {
  const now = new Date('2026-09-29T16:55:00Z');
  const lea = { principalId: 'pr-2', name: 'Lea Hoffmann' };

  it('ends the running period now or with the current TOP', () => {
    const m = meeting({ currentAgendaItemId: 't-3', keeperPeriods: [period({})] });
    expect(currentPosition(m, AGENDA)).toBe(3);
    expect(handoverPreview(m, AGENDA, lea, 'now', now, t, 'de')).toMatch(
      /^Mara Keller \(TOP 1–3\), Lea Hoffmann \(ab TOP 3, \d\d:55\)$/,
    );
    expect(handoverPreview(m, AGENDA, lea, 'next_item', now, t, 'de')).toBe(
      'Mara Keller (TOP 1–3), Lea Hoffmann (ab TOP 4)',
    );
  });

  it('starts from the minute-taker of a meeting without periods', () => {
    const m = meeting({ currentAgendaItemId: null, keeperPeriods: [], startedAt: null });
    expect(currentPosition(m, AGENDA)).toBeNull();
    expect(handoverPreview(m, AGENDA, lea, 'next_item', now, t, 'de')).toMatch(
      /^Pia Protokoll \(\d\d:55–\d\d:55\), Lea Hoffmann \(ab dem nächsten TOP\)$/,
    );
    const nobody = meeting({ protokollantId: null, keeperPeriods: [] });
    expect(handoverPreview(nobody, AGENDA, lea, 'now', now, t, 'de')).toBe('Lea Hoffmann');
  });

  it('knows no position for an item that is not on the agenda', () => {
    expect(currentPosition(meeting({ currentAgendaItemId: 'gone' }), AGENDA)).toBeNull();
  });
});
