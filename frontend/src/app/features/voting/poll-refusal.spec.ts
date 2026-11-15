import { HttpErrorResponse } from '@angular/common/http';

import type { Translate } from '@core/i18n/translations';

import { pollRefusalMessage } from './poll-refusal';

const translate = ((key: string) => key) as Translate;
const refused = (code: string, detail?: string) =>
  new HttpErrorResponse({ status: 422, error: { code, detail } });

describe('pollRefusalMessage', () => {
  it('gives the own text of an end that is too near', () => {
    expect(pollRefusalMessage(refused('circular_window_too_short', 'x'), translate)).toBe(
      'circular.toast.windowTooShort',
    );
    expect(pollRefusalMessage(refused('closes_at_too_soon', 'x'), translate)).toBe('poll.toast.endTooSoon');
  });

  it('gives the server detail of each other refusal, or the plain text', () => {
    expect(pollRefusalMessage(refused('other', 'why'), translate)).toBe('meetings.toast.actionFailed: why');
    expect(pollRefusalMessage(refused('other'), translate)).toBe('meetings.toast.actionFailed');
  });
});
