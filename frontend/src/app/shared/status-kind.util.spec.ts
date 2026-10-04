import { de } from '@core/i18n/translations';
import {
  backupStatus,
  erasureStatus,
  flowColorKind,
  invoiceStatus,
  meetingStatus,
  meetingVoteStatus,
  scanStatus,
  voteResultStatus,
  webhookDeliveryStatus,
  type StatusView,
} from './status-kind.util';

describe('status kinds', () => {
  describe('flowColorKind', () => {
    it.each([
      // The colours of the flow presets.
      ['#4a90d9', 'neutral'], // blue: Entwurf
      ['#e8a33d', 'warn'], // orange: Eingereicht, Prüfung
      ['#9b59b6', 'neutral'], // violet: Abstimmung
      ['#5cb85c', 'accent'], // green: Angenommen
      ['#d9534f', 'error'], // red: Abgelehnt
      // The accent of the design system and the signal colours of the tokens.
      ['#72a384', 'accent'],
      ['#b3261e', 'error'],
      ['#8a5a00', 'warn'],
      ['#dcb065', 'warn'],
      // Edges of the hue ranges.
      ['#ff0055', 'error'], // hue 340: a red that leans to violet
      ['#ff5500', 'warn'], // hue 20: the first orange
    ])('maps %s to %s', (hex, kind) => {
      expect(flowColorKind(hex)).toBe(kind);
    });

    it('treats a yellow-green between warn and accent as neutral', () => {
      // Hue 70: neither clearly yellow nor clearly green.
      expect(flowColorKind('#d4ff00')).toBe('neutral');
    });

    it('treats a cyan beyond the greens as neutral', () => {
      expect(flowColorKind('#00ffff')).toBe('neutral');
    });

    it('treats a grey as neutral, whatever its faint hue', () => {
      expect(flowColorKind('#808080')).toBe('neutral');
      expect(flowColorKind('#7a807c')).toBe('neutral');
      expect(flowColorKind('#000000')).toBe('neutral');
    });

    it('reads the short hex form and ignores the case and spaces', () => {
      expect(flowColorKind('#F00')).toBe('error');
      expect(flowColorKind(' 5CB85C ')).toBe('accent');
    });

    it('treats a missing or invalid colour as neutral', () => {
      expect(flowColorKind(null)).toBe('neutral');
      expect(flowColorKind(undefined)).toBe('neutral');
      expect(flowColorKind('')).toBe('neutral');
      expect(flowColorKind('green')).toBe('neutral');
      expect(flowColorKind('#12345')).toBe('neutral');
    });

    it('reads a hue in the blue sector from the blue channel', () => {
      expect(flowColorKind('#0000ff')).toBe('neutral');
      expect(flowColorKind('#ff00ff')).toBe('neutral'); // hue 300
    });
  });

  describe('voteResultStatus', () => {
    it('shows a passed vote in the accent', () => {
      expect(voteResultStatus('passed')).toEqual({ kind: 'accent', key: 'vote.result.passed' });
    });

    it('shows a rejected vote as an error', () => {
      expect(voteResultStatus('rejected')).toEqual({
        kind: 'error',
        key: 'vote.result.rejected',
      });
    });

    it('shows a tie as a rejection, never as "Stimmengleichheit" (O18)', () => {
      const view = voteResultStatus('tie');
      expect(view).toEqual({ kind: 'error', key: 'vote.result.rejected' });
      expect(de[view.key]).toBe('Abgelehnt');
    });
  });

  const tables: [string, (s: never) => StatusView, Record<string, [string, string]>][] = [
    [
      'meeting',
      meetingStatus as (s: never) => StatusView,
      {
        planned: ['neutral', 'Geplant'],
        live: ['accent', 'Live'],
        closed: ['muted', 'Geschlossen'],
      },
    ],
    [
      'meeting vote',
      meetingVoteStatus as (s: never) => StatusView,
      {
        draft: ['neutral', 'Geplant'],
        open: ['accent', 'Offen'],
        closed: ['neutral', 'Geschlossen'],
        cancelled: ['muted', 'Abgebrochen'],
      },
    ],
    [
      'invoice',
      invoiceStatus as (s: never) => StatusView,
      { open: ['warn', 'Offen'], paid: ['accent', 'Bezahlt'] },
    ],
    [
      'backup',
      backupStatus as (s: never) => StatusView,
      {
        pending: ['neutral', 'Wartet'],
        running: ['neutral', 'Läuft'],
        done: ['accent', 'Fertig'],
        failed: ['error', 'Fehlgeschlagen'],
      },
    ],
    [
      'webhook delivery',
      webhookDeliveryStatus as (s: never) => StatusView,
      {
        never: ['neutral', 'Noch nie'],
        pending: ['neutral', 'Läuft'],
        sent: ['accent', 'Zugestellt'],
        dead: ['error', 'Fehlgeschlagen'],
      },
    ],
    [
      'erasure request',
      erasureStatus as (s: never) => StatusView,
      {
        open: ['warn', 'Offen'],
        executed: ['accent', 'Ausgeführt'],
        rejected: ['error', 'Abgelehnt'],
      },
    ],
    [
      'attachment scan',
      scanStatus as (s: never) => StatusView,
      {
        scanning: ['muted', 'In Prüfung'],
        clean: ['neutral', 'Gescannt'],
        quarantined: ['error', 'Quarantäne'],
      },
    ],
  ];

  describe.each(tables)('%s status', (_name, fn, table) => {
    it.each(Object.entries(table))('maps %s', (status, [kind, label]) => {
      const view = fn(status as never);
      expect(view.kind).toBe(kind);
      expect(de[view.key]).toBe(label);
    });
  });
});
