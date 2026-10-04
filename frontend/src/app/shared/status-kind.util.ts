/**
 * The colour of a status, in one place.
 *
 * The design system shows a status as text in a colour: no dot, no pill. There are five
 * colours and no more, so that the one accent colour keeps its meaning:
 *
 * - `accent`: done and good, or running now (Bewilligt, Live, Bezahlt).
 * - `warn`: it waits for somebody (In Prüfung, Offen for an invoice).
 * - `error`: it failed or was refused (Abgelehnt, Fehlgeschlagen).
 * - `neutral`: an ordinary state (Eingereicht, Geplant, Geschlossen).
 * - `muted`: it is no longer relevant or not yet started (Abgebrochen).
 *
 * The functions below map each status of the platform to a kind, and most of them also
 * to the translation key of its label. `app-status-text` draws the result.
 */
import type { TranslationKey } from '@core/i18n/translations';
import type { MeetingStatus, MeetingVoteStatus, ScanState, VoteResult } from '@core/api/models';
import type { InvoiceStatus } from '../pages/budget/budget-tree.api';
import type {
  BackupStatus,
  ErasureStatus,
  WebhookDeliveryState,
} from '../pages/admin/admin.models';

/** The five status colours of the design system. */
export type StatusKind = 'accent' | 'warn' | 'error' | 'neutral' | 'muted';

/** A status as the UI shows it: the colour and the translation key of the label. */
export interface StatusView {
  kind: StatusKind;
  key: TranslationKey;
}

/**
 * The kind of a configured flow state colour (hex).
 *
 * An admin can give a flow state any colour, but the page shows only the five kinds, so
 * the hue decides: red is `error`, orange and yellow are `warn`, green is `accent`. Every
 * other hue (blue, violet), a grey and a missing or invalid colour are `neutral`.
 */
export function flowColorKind(hex: string | null | undefined): StatusKind {
  const rgb = parseHex(hex);
  if (!rgb) return 'neutral';
  const { h, s } = hueSaturation(rgb);
  // A grey has no hue to go by.
  if (s < 0.15) return 'neutral';
  if (h < 20 || h >= 330) return 'error';
  if (h < 65) return 'warn';
  if (h >= 75 && h < 170) return 'accent';
  return 'neutral';
}

/**
 * The result of a closed vote.
 *
 * A tie is a rejection (O18): the motion did not get a majority. The UI never says
 * "Stimmengleichheit", so a tie shows the label of `rejected`.
 */
export function voteResultStatus(result: VoteResult): StatusView {
  if (result === 'passed') return { kind: 'accent', key: 'vote.result.passed' };
  return { kind: 'error', key: 'vote.result.rejected' };
}

const MEETING: Record<MeetingStatus, StatusView> = {
  planned: { kind: 'neutral', key: 'meetings.status.planned' },
  live: { kind: 'accent', key: 'meetings.status.live' },
  closed: { kind: 'muted', key: 'meetings.status.closed' },
};

/** The status of a meeting. Only a live meeting takes the accent; a closed one is done. */
export function meetingStatus(status: MeetingStatus): StatusView {
  return MEETING[status];
}

const MEETING_VOTE: Record<MeetingVoteStatus, StatusView> = {
  draft: { kind: 'neutral', key: 'meetings.voteStatus.draft' },
  open: { kind: 'accent', key: 'meetings.voteStatus.open' },
  closed: { kind: 'neutral', key: 'meetings.voteStatus.closed' },
  cancelled: { kind: 'muted', key: 'meetings.voteStatus.cancelled' },
};

/** The status of a vote in a meeting. */
export function meetingVoteStatus(status: MeetingVoteStatus): StatusView {
  return MEETING_VOTE[status];
}

const INVOICE: Record<InvoiceStatus, StatusView> = {
  open: { kind: 'warn', key: 'invoices.status.open' },
  paid: { kind: 'accent', key: 'invoices.status.paid' },
};

/** The status of an invoice. An open invoice waits for payment. */
export function invoiceStatus(status: InvoiceStatus): StatusView {
  return INVOICE[status];
}

const BACKUP: Record<BackupStatus, StatusView> = {
  pending: { kind: 'neutral', key: 'admin.backups.status.pending' },
  running: { kind: 'neutral', key: 'admin.backups.status.running' },
  done: { kind: 'accent', key: 'admin.backups.status.done' },
  failed: { kind: 'error', key: 'admin.backups.status.failed' },
};

/** The status of a backup. */
export function backupStatus(status: BackupStatus): StatusView {
  return BACKUP[status];
}

const WEBHOOK: Record<WebhookDeliveryState, StatusView> = {
  never: { kind: 'neutral', key: 'admin.webhook.delivery.state.never' },
  pending: { kind: 'neutral', key: 'admin.webhook.delivery.state.pending' },
  sent: { kind: 'accent', key: 'admin.webhook.delivery.state.sent' },
  dead: { kind: 'error', key: 'admin.webhook.delivery.state.dead' },
};

/** The state of the last delivery of a webhook. */
export function webhookDeliveryStatus(state: WebhookDeliveryState): StatusView {
  return WEBHOOK[state];
}

const ERASURE: Record<ErasureStatus, StatusView> = {
  open: { kind: 'warn', key: 'admin.privacy.status.open' },
  executed: { kind: 'accent', key: 'admin.privacy.status.executed' },
  rejected: { kind: 'error', key: 'admin.privacy.status.rejected' },
};

/** The status of an erasure request (Art. 17). An open request waits for a decision. */
export function erasureStatus(status: ErasureStatus): StatusView {
  return ERASURE[status];
}

const SCAN: Record<ScanState, StatusView> = {
  scanning: { kind: 'muted', key: 'applications.attachments.scan.scanning' },
  clean: { kind: 'neutral', key: 'applications.attachments.scan.clean' },
  quarantined: { kind: 'error', key: 'applications.attachments.scan.quarantined' },
};

/** The virus-scan state of an attachment. */
export function scanStatus(state: ScanState): StatusView {
  return SCAN[state];
}

type Rgb = [number, number, number];

function parseHex(hex: string | null | undefined): Rgb | null {
  if (!hex) return null;
  let h = hex.trim().replace(/^#/, '');
  if (h.length === 3) {
    h = h
      .split('')
      .map((c) => c + c)
      .join('');
  }
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

/** Hue in degrees (0..360) and HSL saturation (0..1) of an sRGB colour. */
function hueSaturation([r8, g8, b8]: Rgb): { h: number; s: number } {
  const r = r8 / 255;
  const g = g8 / 255;
  const b = b8 / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const d = max - min;
  if (d === 0) return { h: 0, s: 0 };
  const l = (max + min) / 2;
  const s = d / (1 - Math.abs(2 * l - 1));
  let h: number;
  if (max === r) h = ((g - b) / d) % 6;
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  h *= 60;
  if (h < 0) h += 360;
  return { h, s };
}
