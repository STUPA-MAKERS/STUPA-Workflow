import { render, screen } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { Meeting } from '@core/api/models';
import { runAxe } from '../../../../testing/a11y';
import { meeting } from '../../../../testing/meeting-fixtures';
import { approvalCandidates, ProtocolApprovalDialogComponent } from './protocol-approval-dialog.component';

const OWN = meeting({ id: 'm-1', gremiumId: 'g-1', date: '2026-10-15', status: 'closed' });

async function setup(opts: { open?: boolean; listMeetings?: jest.Mock; own?: Meeting } = {}) {
  const picked = jest.fn();
  const closed = jest.fn();
  const api = { listMeetings: opts.listMeetings ?? jest.fn(() => of([meeting({ id: 'm-2', title: '34. Sitzung', date: '2026-10-29' })])) };
  const view = await render(ProtocolApprovalDialogComponent, {
    inputs: { open: opts.open ?? true, meeting: opts.own ?? OWN, saving: false },
    on: { picked, closed },
    providers: [{ provide: ApiClient, useValue: api }],
  });
  return { ...view, api, picked, closed, cmp: view.fixture.componentInstance };
}

/** § 000924 */
describe('ProtocolApprovalDialogComponent', () => {
  it('offers the later meetings of the Gremium and picks the next one', async () => {
    const { picked, cmp, container } = await setup();
    expect(cmp.choice()).toBe('m-2');
    expect(await runAxe(container)).toHaveNoViolations();
    cmp.submit();
    expect(picked).toHaveBeenCalledWith('m-2');
  });

  it('reads nothing while it is closed', async () => {
    const { api } = await setup({ open: false });
    expect(api.listMeetings).not.toHaveBeenCalled();
  });

  it('says when no later meeting exists, and picks nothing', async () => {
    const { picked, cmp, fixture } = await setup({ listMeetings: jest.fn(() => of([])), own: { ...OWN, gremiumId: null } });
    fixture.detectChanges();
    expect(screen.getByText('Es gibt noch keine spätere Sitzung dieses Gremiums.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Markieren' })).toBeDisabled();
    cmp.submit();
    expect(picked).not.toHaveBeenCalled();
  });

  it('offers no meeting after a failed read', async () => {
    const failed = await setup({ listMeetings: jest.fn(() => throwError(() => new Error('x'))) });
    expect(failed.cmp.none()).toBe(true);
  });

  it('sends no second pick while the first saves', async () => {
    const { picked, cmp, fixture } = await setup();
    fixture.componentRef.setInput('saving', true);
    cmp.submit();
    expect(picked).not.toHaveBeenCalled();
  });
});

describe('approvalCandidates', () => {
  it('keeps the later meetings in the order of their date, without the own one', () => {
    const all = [
      meeting({ id: 'a', date: '2026-11-12' }),
      meeting({ id: 'b', date: '2026-10-01' }),
      meeting({ id: 'c', date: '2026-10-29' }),
      meeting({ id: 'd', date: null }),
      OWN,
    ];
    expect(approvalCandidates(OWN, all).map((m) => m.id)).toEqual(['c', 'a']);
    expect(approvalCandidates({ ...OWN, date: null }, all).map((m) => m.id)).toEqual(['d', 'b', 'c', 'a']);
  });
});
