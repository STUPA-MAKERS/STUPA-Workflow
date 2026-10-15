import { Subject } from 'rxjs';
import { ChatOutbox } from './chat-outbox';
import type { ChatSend } from './chat.models';

describe('ChatOutbox', () => {
  let calls: { req: ChatSend; answer: Subject<string> }[];
  let delivered: string[];
  let outbox: ChatOutbox<string>;

  beforeEach(() => {
    calls = [];
    delivered = [];
    outbox = new ChatOutbox<string>(
      (req) => {
        const answer = new Subject<string>();
        calls.push({ req, answer });
        return answer;
      },
      (result) => delivered.push(result),
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
});
