import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { LiveVoteService } from '@core/ws/live-vote.service';
import { VotingPageService } from './voting-page.service';

describe('VotingPageService', () => {
  function setup() {
    const opened: { id: string; close: jest.Mock }[] = [];
    const live = {
      open: jest.fn((id: string) => {
        const session = { id, close: jest.fn(), openVote: signal(null) };
        opened.push(session);
        return session;
      }),
    };
    TestBed.configureTestingModule({
      providers: [VotingPageService, { provide: LiveVoteService, useValue: live }],
    });
    return { service: TestBed.inject(VotingPageService), live, opened };
  }

  it('opens one channel per meeting and shares it', () => {
    const { service, live } = setup();
    const a = service.follow('m1');
    expect(service.follow('m1')).toBe(a);
    service.follow('m2');
    expect(live.open).toHaveBeenCalledTimes(2);
    expect([...service.sessions().keys()]).toEqual(['m1', 'm2']);
  });

  it('closes every channel when the page goes away', () => {
    const { service, opened } = setup();
    service.follow('m1');
    service.follow('m2');
    TestBed.resetTestingModule();
    expect(opened.every((s) => s.close.mock.calls.length === 1)).toBe(true);
  });

  it('passes a change to the other pane', () => {
    const { service } = setup();
    const seen: unknown[] = [];
    service.changes$.subscribe((c) => seen.push(c));
    service.notify({ id: 'v1', kind: 'cast' });
    expect(seen).toEqual([{ id: 'v1', kind: 'cast' }]);
  });
});
