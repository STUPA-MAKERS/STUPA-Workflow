import { TestBed } from '@angular/core/testing';
import { WsService } from './ws.service';
import type { ServerMessage } from './ws-messages';

/** Minimaler WebSocket-Mock, der Event-Listener erfasst und manuell feuert. */
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];
  /** Initialer readyState neuer Instanzen (Default OPEN; Tests setzen CONNECTING). */
  static startState = MockWebSocket.OPEN;
  readyState = MockWebSocket.startState;
  sent: string[] = [];
  private listeners: Record<string, ((ev: unknown) => void)[]> = {};

  constructor(public url: string) {
    this.readyState = MockWebSocket.startState;
    MockWebSocket.instances.push(this);
  }

  /** Simuliert den abgeschlossenen Handshake: OPEN + `open`-Event. */
  openNow(): void {
    this.readyState = MockWebSocket.OPEN;
    this.emit('open', {});
  }
  addEventListener(type: string, cb: (ev: unknown) => void): void {
    (this.listeners[type] ??= []).push(cb);
  }
  send(data: string): void {
    this.sent.push(data);
  }
  close(): void {
    this.emit('close', {});
  }
  emit(type: string, ev: unknown): void {
    (this.listeners[type] ?? []).forEach((cb) => cb(ev));
  }
}

describe('WsService', () => {
  let svc: WsService;
  const realWs = globalThis.WebSocket;

  beforeEach(() => {
    MockWebSocket.instances = [];
    MockWebSocket.startState = MockWebSocket.OPEN;
    (globalThis as { WebSocket: unknown }).WebSocket = MockWebSocket;
    svc = TestBed.configureTestingModule({}).inject(WsService);
  });

  afterEach(() => {
    (globalThis as { WebSocket: unknown }).WebSocket = realWs;
  });

  it('opens the meeting channel with a ws URL', () => {
    svc.connectMeeting('m-1');
    expect(MockWebSocket.instances[0].url).toContain('/api/ws/meetings/m-1');
  });

  it('opens the read-only beamer stream', () => {
    svc.connectMeeting('m-1', true);
    expect(MockWebSocket.instances[0].url).toContain('/api/ws/meetings/m-1/beamer');
  });

  it('parses incoming JSON messages', () => {
    const ch = svc.connectMeeting('m-1');
    const received: ServerMessage[] = [];
    ch.messages$.subscribe((m) => received.push(m));
    MockWebSocket.instances[0].emit('message', {
      data: JSON.stringify({ type: 'meeting_state', activeApplicationId: null, status: 'live' }),
    });
    expect(received[0]).toEqual({ type: 'meeting_state', activeApplicationId: null, status: 'live' });
  });

  it('emits an error message on malformed payloads', () => {
    const ch = svc.connectMeeting('m-1');
    const received: ServerMessage[] = [];
    ch.messages$.subscribe((m) => received.push(m));
    MockWebSocket.instances[0].emit('message', { data: '{not json' });
    expect(received[0]).toEqual({ type: 'error', code: 'malformed_message' });
  });

  it('serialises client messages on send', () => {
    const ch = svc.connectMeeting('m-1');
    ch.send({ type: 'cast', voteId: 'v1', choice: 'yes' });
    expect(MockWebSocket.instances[0].sent[0]).toBe(
      JSON.stringify({ type: 'cast', voteId: 'v1', choice: 'yes' }),
    );
  });

  it('queues frames sent while CONNECTING and flushes them on open', () => {
    // Realer Socket startet im Zustand CONNECTING. Ein synchron nach dem
    // Verbindungsaufbau gesendetes `subscribe` (LiveVoteSession-Resync) darf
    // NICHT verworfen werden — ohne Puffer ginge es auf echtem Socket verloren.
    MockWebSocket.startState = MockWebSocket.CONNECTING;
    const ch = svc.connectMeeting('m-1');
    const sock = MockWebSocket.instances[0];

    ch.send({ type: 'subscribe' });
    ch.send({ type: 'cast', voteId: 'v1', choice: 'yes' });
    // Vor dem Handshake darf nichts auf der Leitung sein.
    expect(sock.sent).toEqual([]);

    sock.openNow();
    // Beim Öffnen werden die gepufferten Frames in Reihenfolge geflusht.
    expect(sock.sent).toEqual([
      JSON.stringify({ type: 'subscribe' }),
      JSON.stringify({ type: 'cast', voteId: 'v1', choice: 'yes' }),
    ]);
  });

  it('drops frames sent after the socket has closed', () => {
    const ch = svc.connectMeeting('m-1');
    const sock = MockWebSocket.instances[0];
    sock.readyState = MockWebSocket.CLOSED;
    ch.send({ type: 'subscribe' });
    expect(sock.sent).toEqual([]);
  });
});
