import { TestBed } from '@angular/core/testing';
import { WsService } from './ws.service';
import type { ServerMessage } from './ws-messages';
import { createLocationMock, provideLocationMock } from '../../../testing/location-mock';

/** Minimal WebSocket mock that captures event listeners and fires them manually. */
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];
  /** Initial readyState of new instances (default OPEN; tests set CONNECTING). */
  static startState = MockWebSocket.OPEN;
  readyState = MockWebSocket.startState;
  sent: string[] = [];
  private listeners: Record<string, ((ev: unknown) => void)[]> = {};

  constructor(public url: string) {
    this.readyState = MockWebSocket.startState;
    MockWebSocket.instances.push(this);
  }

  /** Simulates the completed handshake: OPEN + `open` event. */
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
    // Mock `LOCATION` via DI — jsdom ≥26 no longer lets `window.location` be
    // redefined. Default: http://localhost.
    svc = TestBed.configureTestingModule({
      providers: [provideLocationMock(createLocationMock())],
    }).inject(WsService);
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
    // A real socket starts in state CONNECTING. A `subscribe` sent synchronously
    // right after connecting (LiveVoteSession resync) must NOT be dropped —
    // without the buffer it would be lost on a real socket.
    MockWebSocket.startState = MockWebSocket.CONNECTING;
    const ch = svc.connectMeeting('m-1');
    const sock = MockWebSocket.instances[0];

    ch.send({ type: 'subscribe' });
    ch.send({ type: 'cast', voteId: 'v1', choice: 'yes' });
    // Nothing may be on the wire before the handshake.
    expect(sock.sent).toEqual([]);

    sock.openNow();
    // On open the buffered frames are flushed in order.
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

  it('completes the stream when the socket closes', () => {
    const ch = svc.connectMeeting('m-1');
    let completed = false;
    ch.messages$.subscribe({ complete: () => (completed = true) });
    MockWebSocket.instances[0].emit('close', {});
    expect(completed).toBe(true);
  });

  it('emits a socket_error message on the error event', () => {
    const ch = svc.connectMeeting('m-1');
    const received: ServerMessage[] = [];
    ch.messages$.subscribe((m) => received.push(m));
    MockWebSocket.instances[0].emit('error', {});
    expect(received[0]).toEqual({ type: 'error', code: 'socket_error' });
  });

  it('closes the underlying socket via channel.close()', () => {
    const ch = svc.connectMeeting('m-1');
    const closeSpy = jest.spyOn(MockWebSocket.instances[0], 'close');
    ch.close();
    expect(closeSpy).toHaveBeenCalled();
  });

  /** Fresh service with its own `LOCATION` (protocol/host per test). */
  function serviceAt(protocol: string, host: string): WsService {
    TestBed.resetTestingModule();
    return TestBed.configureTestingModule({
      providers: [provideLocationMock(createLocationMock({ protocol, host }))],
    }).inject(WsService);
  }

  it('uses the wss scheme on https origins', () => {
    serviceAt('https:', 'example.org').connectMeeting('m-secure');
    expect(MockWebSocket.instances[0].url).toBe('wss://example.org/api/ws/meetings/m-secure');
  });

  it('uses the ws scheme on http origins', () => {
    serviceAt('http:', 'example.org').connectMeeting('m-plain');
    expect(MockWebSocket.instances[0].url).toBe('ws://example.org/api/ws/meetings/m-plain');
  });
});
