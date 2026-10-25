import { Subject, of, throwError } from 'rxjs';
import { ChatOutbox, draftDropper, filesRefused, missingFiles, sendErrorKey } from './chat-outbox';
import type { ChatAttachment, ChatSend } from './chat.models';

const FILE_A: ChatAttachment = { id: 'a', filename: 'a.png', mime: 'image/png', size: 1, url: '/a', scanState: 'scanning' };
const FILE_B: ChatAttachment = { id: 'b', filename: 'b.pdf', mime: 'application/pdf', size: 2, url: '/b', scanState: 'clean' };

function missing(...ids: string[]) {
  return {
    status: 422,
    error: { code: 'draft_attachments_missing', errors: ids.map((id) => ({ field: `attachmentIds.${id}` })) },
  };
}

describe('ChatOutbox', () => {
  let calls: { req: ChatSend; answer: Subject<string> }[];
  let delivered: string[];
  let failures: unknown[];
  let outbox: ChatOutbox<string>;

  beforeEach(() => {
    calls = [];
    delivered = [];
    failures = [];
    outbox = new ChatOutbox<string>(
      (req) => {
        const answer = new Subject<string>();
        calls.push({ req, answer });
        return answer;
      },
      (result) => delivered.push(result),
      (err) => failures.push(err),
    );
  });

  it('shows a sent message at once and hands the answer over', () => {
    outbox.send({ body: 'Hallo', visibility: 'internal' });
    expect(outbox.messages()).toEqual([
      expect.objectContaining({ body: 'Hallo', own: true, visibility: 'internal', state: 'sending', author: null }),
    ]);
    calls[0].answer.next('server');
    expect(outbox.messages()).toEqual([]);
    expect(delivered).toEqual(['server']);
  });

  it('keeps a failed message and sends it again on retry', () => {
    outbox.send({ body: 'x' });
    expect(outbox.messages()[0].visibility).toBeNull();
    calls[0].answer.error(new Error('offline'));
    const id = outbox.messages()[0].id;
    expect(outbox.messages()[0].state).toBe('failed');

    outbox.retry(id);
    expect(outbox.messages()[0].state).toBe('sending');
    expect(calls[1].req).toEqual({ body: 'x' });
    calls[1].answer.next('ok');
    expect(outbox.messages()).toEqual([]);
    expect(delivered).toEqual(['ok']);
  });

  it('ignores a retry of an unknown id', () => {
    outbox.retry('nope');
    expect(calls).toEqual([]);
  });

  it('drops a late answer after clear', () => {
    outbox.send({ body: 'x' });
    outbox.clear();
    expect(outbox.messages()).toEqual([]);
    calls[0].answer.next('late');
    expect(delivered).toEqual([]);
  });

  /** A failure marks only its own message. */
  it('gives every message its own id', () => {
    outbox.send({ body: 'a' });
    outbox.send({ body: 'b' });
    const [a, b] = outbox.messages();
    expect(a.id).not.toBe(b.id);
    calls[1].answer.error(new Error('x'));
    expect(outbox.messages().map((m) => m.state)).toEqual(['sending', 'failed']);
  });

  it('tells the consumer why a send failed', () => {
    outbox.send({ body: 'x' });
    const err = { status: 422 };
    calls[0].answer.error(err);
    expect(failures).toEqual([err]);
  });

  /** A discarded message cannot be sent again. */
  it('discards a failed message, and a late error of a cleared one stays quiet', () => {
    outbox.send({ body: 'x' });
    calls[0].answer.error(new Error('offline'));
    const id = outbox.messages()[0].id;
    outbox.discard(id);
    expect(outbox.messages()).toEqual([]);
    outbox.retry(id);
    expect(calls).toHaveLength(1);
    outbox.discard('nope');

    outbox.send({ body: 'y' });
    outbox.clear();
    calls[1].answer.error(new Error('late'));
    expect(outbox.messages()).toEqual([]);
    expect(failures).toHaveLength(1);
  });

  it('works without a failure callback', () => {
    const answer = new Subject<string>();
    const quiet = new ChatOutbox<string>(() => answer, () => undefined);
    quiet.send({ body: 'x' });
    answer.error(new Error('x'));
    expect(quiet.messages()[0].state).toBe('failed');
  });

  it('names the reason of a failed send', () => {
    const tooLong = { status: 422, error: { errors: [{ field: 'body.body', msg: 'String should have at most 10000 characters' }] } };
    expect(sendErrorKey(tooLong, 'chat.failed')).toBe('chat.error.tooLong');
    expect(sendErrorKey({ status: 413 }, 'chat.failed')).toBe('chat.error.tooLong');
    expect(sendErrorKey({ status: 403 }, 'chat.failed')).toBe('chat.error.forbidden');
    expect(sendErrorKey({ status: 500 }, 'chat.failed')).toBe('chat.failed');
    expect(sendErrorKey(null, 'chat.failed')).toBe('chat.failed');
  });

  it('takes no other 422 for a long body', () => {
    const v = (errors: unknown) => ({ status: 422, error: { code: 'validation_error', errors } });
    expect(sendErrorKey({ status: 422 }, 'chat.failed')).toBe('chat.failed');
    expect(sendErrorKey({ status: 422, error: { code: 'ticket_closed' } }, 'chat.failed')).toBe('chat.failed');
    expect(sendErrorKey(v([{ field: 'body', msg: 'Value error, A message needs a text or at least one file.' }]), 'chat.failed')).toBe('chat.failed');
    expect(sendErrorKey(v([{ field: 'body.draftToken', msg: 'Field required' }]), 'chat.failed')).toBe('chat.failed');
    expect(sendErrorKey(v([null, { field: 1, msg: 'at most' }, { field: 'body.body', msg: 3 }]), 'chat.failed')).toBe('chat.failed');
  });

  it('keeps a message with no text and no file left failed, without a resend', () => {
    outbox.send({ body: ' ', attachmentIds: ['a'], draftToken: 'tok', files: [FILE_A] });
    calls[0].answer.error(missing('a'));
    const msg = outbox.messages()[0];
    outbox.retry(msg.id);
    expect(calls).toHaveLength(1);
    expect(outbox.messages()[0].state).toBe('failed');
    expect(failures).toHaveLength(2);
    expect(sendErrorKey(failures[1], 'chat.failed')).toBe('chat.error.filesMissing');
  });

  it('names a lost file before a long body', () => {
    expect(sendErrorKey(missing('a'), 'chat.failed')).toBe('chat.error.filesMissing');
  });

  it('reads the ids of a 422 draft_attachments_missing', () => {
    expect(missingFiles(missing('a', 'b'))).toEqual(new Set(['a', 'b']));
    expect(
      missingFiles({
        status: 422,
        error: { code: 'draft_attachments_missing', errors: [null, { field: 'draftToken' }, { field: 3 }] },
      }),
    ).toEqual(new Set());
    expect(missingFiles({ status: 422, error: { code: 'draft_attachments_missing' } })).toEqual(new Set());
    expect(missingFiles({ status: 422, error: { code: 'other' } })).toBeNull();
    expect(missingFiles({ status: 500 })).toBeNull();
    expect(missingFiles(null)).toBeNull();
  });

  it('shows the files of a pending message, marks lost ones and resends the others', () => {
    outbox.send({ body: '', attachmentIds: ['a', 'b'], draftToken: 'tok', files: [FILE_A, FILE_B] });
    expect(outbox.messages()[0].attachments).toEqual([FILE_A, FILE_B]);
    calls[0].answer.error(missing('a'));
    const msg = outbox.messages()[0];
    expect(msg.state).toBe('failed');
    expect(msg.attachments).toEqual([{ ...FILE_A, lost: true }, FILE_B]);
    outbox.retry(msg.id);
    expect(calls[1].req.attachmentIds).toEqual(['b']);
    expect(calls[1].req.draftToken).toBe('tok');
  });

  /** The other pending message keeps its files. */
  it('marks lost files of a message without files without a change', () => {
    outbox.send({ body: 'x' });
    outbox.send({ body: 'y', attachmentIds: ['b'], draftToken: 't', files: [FILE_B] });
    calls[0].answer.error(missing('a'));
    expect(outbox.messages()[0].attachments).toBeUndefined();
    expect(outbox.messages()[1].attachments).toEqual([FILE_B]);
    outbox.retry(outbox.messages()[0].id);
    expect(calls[2].req.attachmentIds).toEqual([]);
  });

  it('deletes the drafts of a discarded message, and none without files or token', () => {
    const drop = jest.fn();
    const answer = new Subject<string>();
    const box = new ChatOutbox<string>(() => answer, () => undefined, () => undefined, drop);
    box.send({ body: '', attachmentIds: ['a'], draftToken: 'tok', files: [FILE_A] });
    box.send({ body: 'ohne' });
    box.send({ body: '', attachmentIds: ['a'], draftToken: null });
    answer.error(new Error('x'));
    for (const m of box.messages()) box.discard(m.id);
    expect(drop).toHaveBeenCalledTimes(1);
    expect(drop).toHaveBeenCalledWith(['a'], 'tok');
  });

  it('works without a drop callback', () => {
    const answer = new Subject<string>();
    const box = new ChatOutbox<string>(() => answer, () => undefined);
    box.send({ body: '', attachmentIds: ['a'], draftToken: 'tok' });
    answer.error(new Error('x'));
    box.discard(box.messages()[0].id);
    expect(box.messages()).toEqual([]);
  });

  it('drops drafts through the API and ignores a failed delete', () => {
    const del = jest.fn((id: string) => (id === 'bad' ? throwError(() => new Error('x')) : of(undefined)));
    draftDropper({ deleteDraftAttachment: del })(['a', 'bad'], 'tok');
    expect(del).toHaveBeenCalledWith('a', 'tok');
    expect(del).toHaveBeenCalledWith('bad', 'tok');
  });

  /** The retry sends the text alone. Without files or without a token there is nothing to drop. */
  it('marks every file lost when an anonymized thread refuses them, and drops their drafts', () => {
    const drop = jest.fn();
    const sent: ChatSend[] = [];
    const answers: Subject<string>[] = [];
    const errors: unknown[] = [];
    const box = new ChatOutbox<string>(
      (req) => {
        sent.push(req);
        const a = new Subject<string>();
        answers.push(a);
        return a;
      },
      () => undefined,
      (err) => errors.push(err),
      drop,
    );
    const refused = { status: 422, error: { code: 'application_anonymized', errors: [] } };
    box.send({ body: 'Text', attachmentIds: ['a', 'b'], draftToken: 'tok', files: [FILE_A, FILE_B] });
    answers[0].error(refused);
    const msg = box.messages()[0];
    expect(msg.state).toBe('failed');
    expect(msg.attachments).toEqual([{ ...FILE_A, lost: true }, { ...FILE_B, lost: true }]);
    expect(drop).toHaveBeenCalledWith(['a', 'b'], 'tok');
    expect(sendErrorKey(errors[0], 'chat.failed')).toBe('chat.error.filesRefused');
    box.retry(msg.id);
    expect(sent[1].attachmentIds).toEqual([]);

    box.send({ body: 'ohne' });
    answers[2].error({ status: 422, error: { code: 'ticket_anonymized' } });
    box.send({ body: '', attachmentIds: ['c'], draftToken: null });
    answers[3].error({ status: 422, error: { code: 'ticket_anonymized' } });
    expect(drop).toHaveBeenCalledTimes(1);
  });

  it('knows the refusals of an anonymized thread', () => {
    expect(filesRefused({ status: 422, error: { code: 'application_anonymized' } })).toBe(true);
    expect(filesRefused({ status: 422, error: { code: 'ticket_anonymized' } })).toBe(true);
    expect(filesRefused({ status: 409, error: { code: 'ticket_anonymized' } })).toBe(false);
    expect(filesRefused({ status: 422 })).toBe(false);
    expect(filesRefused(null)).toBe(false);
  });
});
