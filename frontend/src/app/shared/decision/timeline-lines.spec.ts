import { de } from '@core/i18n/translations';
import type { Translate } from '@core/i18n/translations';
import { amountChangeLines, forcedLine, orderEventText, outsideDecisionLines } from './timeline-lines';

const t: Translate = (key, params) =>
  Object.entries(params ?? {}).reduce(
    (text, [k, v]) => text.replaceAll(`{${k}}`, String(v)),
    de[key] as string,
  );
const plain = (lines: readonly string[]) => lines.map((l) => l.replace(/\u00a0/g, ' '));

describe('timeline lines', () => {
  /** Spec 001602: result, date and Gremium; the counts only when given. */
  it('names an outside decision with and without the optional values', () => {
    expect(
      outsideDecisionLines(
        { result: 'passed', meetingDate: '2026-11-18', gremiumName: 'StuPa', yes: 5, no: 0, abstain: 2 },
        'de-DE',
        t,
      ),
    ).toEqual(['Ergebnis: Angenommen', 'Sitzung vom 18.11.2026 · StuPa', 'Ja 5 · Nein 0 · Enthaltung 2']);
    expect(outsideDecisionLines({ result: 'failed', meetingDate: '2026-11-18' }, 'de-DE', t)).toEqual([
      'Ergebnis: Abgelehnt',
      'Beschluss vom 18.11.2026',
    ]);
  });

  /** Spec 001621: the old and the new amount, the reason, the decision. */
  it('names an amount change, without the reason in the applicant view', () => {
    expect(
      plain(
        amountChangeLines(
          { previousAmount: '100.00', approvedAmount: '1222.50', reason: 'Mehrkosten', decisionDate: '2026-11-18', gremiumName: 'StuPa' },
          'de-DE',
          'EUR',
          t,
        ),
      ),
    ).toEqual(['Bisher: 100,00 € · Neu: 1.222,50 €', 'Mehrkosten', 'Beschluss vom 18.11.2026 · StuPa']);
    expect(
      plain(amountChangeLines({ previousAmount: null, approvedAmount: '5.00', decisionDate: '2026-11-18' }, 'de-DE', 'EUR', t)),
    ).toEqual(['Bisher: — · Neu: 5,00 €', 'Beschluss vom 18.11.2026']);
    expect(plain(amountChangeLines({ approvedAmount: '5.00' }, 'de-DE', 'EUR', t))).toEqual(['Bisher: — · Neu: 5,00 €']);
  });

  /** Specs 001650, 001652: a known reason, else "Ohne Grund". */
  it('names the reason of a forced state', () => {
    expect(forcedLine('applicant_error', t)).toBe('Status erzwungen · Fehlbedienung Antragsteller:in');
    expect(forcedLine(null, t)).toBe('Status erzwungen · Ohne Grund');
    expect(forcedLine('gone', t)).toBe('Status erzwungen · Ohne Grund');
  });

  /** §F/finance/orders/002866: the create, a status change and the delete of a Bestellung. */
  it('names the event of a Bestellung with its Bezeichnung and its number', () => {
    const base = { orderId: 'o-1', number: 'B-7K3QX9MD', title: 'Beamer' };
    expect(orderEventText({ ...base, change: 'created' }, t)).toEqual({
      title: 'Bestellung angelegt',
      body: 'Beamer · B-7K3QX9MD',
    });
    expect(orderEventText({ ...base, change: 'deleted', number: '' }, t)).toEqual({
      title: 'Bestellung gelöscht',
      body: 'Beamer',
    });
    expect(orderEventText({ ...base, change: 'status', toStatus: 'delivered' }, t).title).toBe('Bestellung: Geliefert');
    expect(orderEventText({ ...base, change: 'status', toStatus: 'other' }, t).title).toBe('Bestellung: other');
    expect(orderEventText({ ...base, change: 'status' }, t).title).toBe('Bestellung: ');
  });
});
