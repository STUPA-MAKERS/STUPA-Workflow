import { By } from '@angular/platform-browser';
import { render } from '@testing-library/angular';
import { Subject, of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { ApplicationComment } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { ChatComponent } from '@shared/ui';
import { OrderCommentsDirective } from './order-comments.directive';

const comment = (over: Partial<ApplicationComment> = {}): ApplicationComment => ({
  id: 'c-1',
  author: 'Finanzreferat',
  authorKind: 'principal',
  authorInfo: null,
  body: 'Bitte bestellen.',
  visibility: 'public',
  isPublic: true,
  isOwn: false,
  at: '2026-06-05T12:00:00Z',
  attachments: [],
  mentions: [],
  ...over,
});

async function setup(manage = true) {
  localStorage.setItem('ap.locale', 'de');
  const api = {
    comments: jest.fn(() =>
      of([
        comment(),
        comment({ id: 'c-2', author: null, authorKind: 'applicant', isOwn: true }),
        comment({ id: 'c-3', author: null }),
        comment({ id: 'c-4', authorInfo: { kind: 'principal', principalId: 'p-1', displayName: 'Ada' } as never }),
      ]),
    ),
    mentionable: jest.fn(() => of([])),
    addComment: jest.fn(() => of(comment({ id: 'c-9', body: 'Neu' }))),
    updateComment: jest.fn(() => of(comment({ body: 'Geändert' }))),
    deleteComment: jest.fn(() => of(undefined)),
    deleteDraftAttachment: jest.fn(() => of(undefined)),
  };
  const view = await render('<app-chat [appOrderComments]="id" draftKey="application.a-1" />', {
    imports: [ChatComponent, OrderCommentsDirective],
    componentProperties: { id: 'a-1' },
    providers: [
      { provide: ApiClient, useValue: api },
      { provide: AuthService, useValue: { can: () => manage } },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cmp = view.fixture.debugElement.query(By.directive(OrderCommentsDirective)).injector.get(OrderCommentsDirective) as any;
  const toast = jest.spyOn(view.fixture.debugElement.injector.get(ToastService), 'show');
  return { ...view, cmp, api, toast };
}

describe('OrderCommentsDirective', () => {
  afterEach(() => localStorage.clear());

  /** §F/finance/orders/002935: the comments of the detail are the comments of the Antrag. */
  it('reads the comments of the Antrag and posts a new one to the Antrag', async () => {
    const { cmp, api } = await setup();
    expect(api.comments).toHaveBeenCalledWith('a-1', { quiet: true });
    expect(api.mentionable).toHaveBeenCalledWith('a-1');
    expect(cmp.loading()).toBe(false);
    expect(cmp.visibilities()).toEqual(['internal', 'public']);
    const messages = cmp.messages();
    expect(messages.map((m: { author: { displayName: string } }) => m.author.displayName)).toEqual([
      'Finanzreferat',
      expect.any(String),
      'Gremium',
      expect.any(String),
    ]);
    expect(messages[0]).toMatchObject({ id: 'c-1', own: false, canEdit: true, visibility: 'public' });
    expect(messages[3].author.principalId).toBe('p-1');
    cmp.send({ body: 'Neu', visibility: 'internal', mentions: ['p-1'] });
    expect(api.addComment).toHaveBeenCalledWith(
      'a-1',
      'Neu',
      'internal',
      expect.objectContaining({ body: 'Neu', visibility: 'internal' }),
      ['p-1'],
    );
    expect(cmp.messages().map((m: { id: string }) => m.id)).toContain('c-9');
  });

  it('posts a public comment without application.manage and lets only the author change one', async () => {
    const { cmp, api } = await setup(false);
    expect(cmp.visibilities()).toEqual([]);
    expect(cmp.messages().map((m: { canEdit: boolean }) => m.canEdit)).toEqual([false, true, false, false]);
    cmp.send({ body: 'Neu', visibility: 'internal' });
    expect(api.addComment).toHaveBeenCalledWith('a-1', 'Neu', 'public', { body: 'Neu' }, undefined);
  });

  it('says when a comment could not be sent', async () => {
    const { cmp, api, toast } = await setup();
    api.addComment.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    cmp.send({ body: 'Neu' });
    expect(toast).toHaveBeenCalledWith(expect.any(String), 'error');
  });

  it('changes and deletes a comment, and says when that fails', async () => {
    const { cmp, api, toast } = await setup();
    const restore = jest.fn();
    cmp.edit({ id: 'c-1', body: 'Geändert', mentions: [] });
    expect(api.updateComment).toHaveBeenCalledWith('a-1', 'c-1', 'Geändert', []);
    expect(cmp.messages()[0].body).toBe('Geändert');
    api.updateComment.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    cmp.edit({ id: 'c-1', body: 'x', restore });
    expect(restore).toHaveBeenCalled();
    api.updateComment.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    cmp.edit({ id: 'c-1', body: 'x' });
    expect(toast).toHaveBeenCalledTimes(2);
    api.deleteComment.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    cmp.remove({ id: 'c-2' });
    expect(toast).toHaveBeenCalledTimes(3);
    expect(cmp.messages()).toHaveLength(4);
    cmp.remove({ id: 'c-2' });
    expect(api.deleteComment).toHaveBeenLastCalledWith('a-1', 'c-2');
    expect(cmp.messages()).toHaveLength(3);
  });

  it('reads the scan states again and keeps the thread when that fails', async () => {
    const { cmp, api } = await setup();
    cmp.refresh();
    expect(api.comments).toHaveBeenCalledTimes(2);
    api.comments.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    cmp.refresh();
    expect(cmp.messages()).toHaveLength(4);
  });

  it('shows an empty thread when the reads fail, and drops the answer of an older Antrag', async () => {
    const { cmp, api, rerender } = await setup();
    const slow = new Subject<ApplicationComment[]>();
    api.comments.mockReturnValueOnce(slow as never);
    await rerender({ componentProperties: { id: 'a-2' } });
    expect(cmp.loading()).toBe(true);
    api.comments.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    api.mentionable.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    await rerender({ componentProperties: { id: 'a-3' } });
    slow.next([comment()]);
    expect(cmp.loading()).toBe(false);
    expect(cmp.messages()).toEqual([]);
    expect(cmp.mentionables()).toEqual([]);
  });
});
