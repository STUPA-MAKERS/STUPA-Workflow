import { Subject } from 'rxjs';
import { ChatOutbox, sendErrorKey } from './chat-outbox';
import type { ChatSend } from './chat.models';

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

  it('gives every message its own id', () => {
    outbox.send({ body: 'a' });
    outbox.send({ body: 'b' });
    const [a, b] = outbox.messages();
    expect(a.id).not.toBe(b.id);
    // A failure marks only its own message.
    calls[1].answer.error(new Error('x'));
    expect(outbox.messages().map((m) => m.state)).toEqual(['sending', 'failed']);
  });

  it('tells the consumer why a send failed', () => {
    outbox.send({ body: 'x' });
    const err = { status: 422 };
    calls[0].answer.error(err);
    expect(failures).toEqual([err]);
  });

  it('discards a failed message, and a late error of a cleared one stays quiet', () => {
    outbox.send({ body: 'x' });
    calls[0].answer.error(new Error('offline'));
    const id = outbox.messages()[0].id;
    outbox.discard(id);
    expect(outbox.messages()).toEqual([]);
    // A discarded message cannot be sent again.
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
    expect(sendErrorKey({ status: 422 }, 'chat.failed')).toBe('chat.error.tooLong');
    expect(sendErrorKey({ status: 413 }, 'chat.failed')).toBe('chat.error.tooLong');
    expect(sendErrorKey({ status: 403 }, 'chat.failed')).toBe('chat.error.forbidden');
    expect(sendErrorKey({ status: 500 }, 'chat.failed')).toBe('chat.failed');
    expect(sendErrorKey(null, 'chat.failed')).toBe('chat.failed');
  });
});
