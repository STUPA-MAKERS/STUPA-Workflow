import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { USE_MOCK_API } from '@core/api/api.config';
import { render, screen } from '@testing-library/angular';
import { type CanvasNode, GraphCanvasComponent, LABEL_ZOOM, NUDGE } from './graph-canvas.component';
import { type Body, SETTLE_STEPS } from './graph-layout';
import type { GraphLine } from './graph.util';

const node = (key: string, over: Partial<CanvasNode> = {}): CanvasNode => ({
  key,
  kind: 'meeting',
  icon: 'users',
  title: `Titel ${key}`,
  name: `Sitzung: Titel ${key}`,
  muted: false,
  near: '',
  ...over,
});
const line = (a: string, b: string, source: GraphLine['source'] = 'link'): GraphLine => ({
  key: `${source}|${a}|${b}`,
  a,
  b,
  source,
});

const NODES = [node('a'), node('b'), node('c', { muted: true, kind: 'invoice', icon: 'receipt' })];
const LINES = [line('a', 'b'), line('b', 'c', 'builtin'), line('a', 'gone')];

/** The frames that the component asked for; `run` plays them until none is left. */
function frames() {
  const queue: FrameRequestCallback[] = [];
  const door = GraphCanvasComponent.prototype as unknown as {
    nextFrame: (cb: FrameRequestCallback) => number;
    dropFrame: (frame: number) => void;
  };
  const request = jest.spyOn(door, 'nextFrame').mockImplementation((cb) => queue.push(cb));
  const cancel = jest.spyOn(door, 'dropFrame').mockImplementation(() => undefined);
  const run = (): number => {
    let played = 0;
    while (queue.length > 0) {
      (queue.shift() as FrameRequestCallback)(0);
      played += 1;
    }
    return played;
  };
  return { queue, request, cancel, run };
}

function pointer(target: Element, id: number, x: number, y: number, type = 'pointerdown'): PointerEvent {
  return { target, currentTarget: target, pointerId: id, clientX: x, clientY: y, type } as unknown as PointerEvent;
}

async function setup(opts: { reduce?: boolean; nodes?: readonly CanvasNode[]; lines?: readonly GraphLine[]; selected?: string | null } = {}) {
  localStorage.setItem('ap.locale', 'de');
  document.documentElement.setAttribute('data-display-motion', opts.reduce === false ? 'full' : 'reduce');
  const chosen = jest.fn();
  const r = await render(GraphCanvasComponent, {
    providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
    inputs: {
      nodes: opts.nodes ?? NODES,
      lines: opts.lines ?? LINES,
      selected: opts.selected ?? null,
      label: 'Graph mit 3 Elementen',
    },
    on: { chosen },
  });
  const cmp = r.fixture.componentInstance;
  const surface = r.container.querySelector('.gc') as HTMLElement;
  const button = (key: string): HTMLElement => r.container.querySelector(`[data-key="${key}"]`) as HTMLElement;
  return { ...r, cmp, chosen, surface, button };
}

describe('GraphCanvasComponent', () => {
  let width: jest.SpyInstance;
  let height: jest.SpyInstance;

  beforeEach(() => {
    width = jest.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800);
    height = jest.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(600);
  });

  afterEach(() => {
    width.mockRestore();
    height.mockRestore();
    jest.restoreAllMocks();
    document.documentElement.removeAttribute('data-display-motion');
    localStorage.clear();
  });

  /** § F/collaboration/graph/001427: with reduced motion the layout runs to its end before the paint. */
  it('shows the final layout at once with reduced motion', async () => {
    const f = frames();
    const { cmp, container, surface } = await setup();
    expect(f.request).not.toHaveBeenCalled();
    expect(cmp.bodies().map((b) => b.id)).toEqual(['a', 'b', 'c']);
    expect(cmp.bodies().every((b) => b.vx === 0 && b.vy === 0)).toBe(true);
    expect(surface).toHaveClass('gc--still');
    expect(container.querySelectorAll('.gc__node')).toHaveLength(3);
  });

  /** § F/collaboration/graph/001426: the layout settles frame by frame, and the nodes keep their place. */
  it('settles over frames and keeps the nodes that show when new nodes arrive', async () => {
    const f = frames();
    const { cmp, fixture, surface, button } = await setup({ reduce: false, nodes: [node('a'), node('b')], lines: [line('a', 'b')] });
    expect(surface).not.toHaveClass('gc--still');
    expect(f.queue).toHaveLength(1);
    expect(f.run()).toBe(SETTLE_STEPS);
    expect(f.queue).toHaveLength(0);

    const before = cmp.bodies();
    const elementA = button('a');
    fixture.componentRef.setInput('nodes', [node('a'), node('b'), node('n1'), node('n2')]);
    fixture.componentRef.setInput('lines', [line('a', 'b'), line('a', 'n1')]);
    fixture.detectChanges();
    // Before the next frame the old nodes are where they were.
    expect(cmp.bodies().slice(0, 2)).toEqual(before);
    expect(button('a')).toBe(elementA);
    expect(cmp.order().get('n1')).toBe(0);
    expect(cmp.order().get('n2')).toBe(1);
    expect(cmp.delay('n2')).toBe('14ms');
    expect(cmp.delay('a')).toBe('0ms');
    expect(f.queue).toHaveLength(1);
    f.run();
    expect(cmp.bodies()).toHaveLength(4);
  });

  it('asks for one frame at a time and cancels it when it ends', async () => {
    const f = frames();
    const { cmp, fixture } = await setup({ reduce: false });
    (cmp as unknown as { run: () => void }).run();
    expect(f.queue).toHaveLength(1);
    fixture.destroy();
    expect(f.cancel).toHaveBeenCalled();
  });

  it('draws the lines between the nodes that show, the fixed relations dashed', async () => {
    const { container, cmp } = await setup();
    const lines = container.querySelectorAll('.gc__line');
    expect(lines).toHaveLength(2);
    expect(lines[0]).not.toHaveClass('gc__line--builtin');
    expect(lines[1]).toHaveClass('gc__line--builtin');
    const a = cmp.bodies()[0];
    expect(lines[0].getAttribute('x1')).toBe(String(a.x));
    expect(container.querySelector('.gc__lines')).toHaveAttribute('aria-hidden', 'true');
  });

  /** § F/collaboration/graph/001428: one group with a label; § 001430: the icon and the kind. */
  it('names the drawing and each node, and marks an element without access', async () => {
    const { container, button } = await setup();
    expect(screen.getByRole('group', { name: 'Graph mit 3 Elementen' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sitzung: Titel a' })).toBe(button('a'));
    expect(button('a')).toHaveAttribute('data-kind', 'meeting');
    expect(button('a').querySelector('app-icon')).not.toBeNull();
    expect(button('a').querySelector('.gc__label')).toHaveTextContent('Titel a');
    expect(button('c')).toHaveClass('gc__node--muted');
    expect(button('a')).not.toHaveClass('gc__node--muted');
    expect(container.querySelector('.gc')).toHaveClass('gc--labels');
  });

  /** § F/collaboration/graph/001429: a press chooses, the other nodes dim. */
  it('emits the pressed node and dims the nodes that are no neighbours', async () => {
    const { chosen, button, fixture, container } = await setup({ nodes: [...NODES, node('d')] });
    button('a').click();
    expect(chosen).toHaveBeenCalledWith('a');
    expect(button('a')).toHaveAttribute('aria-pressed', 'false');
    expect(container.querySelector('.gc__node--dim')).toBeNull();

    fixture.componentRef.setInput('selected', 'a');
    fixture.detectChanges();
    expect(button('a')).toHaveAttribute('aria-pressed', 'true');
    expect(button('a')).toHaveClass('gc__node--chosen', 'gc__node--lit');
    expect(button('b')).toHaveClass('gc__node--lit');
    expect(button('b')).not.toHaveClass('gc__node--dim');
    expect(button('c')).toHaveClass('gc__node--dim');
    expect(button('d')).toHaveClass('gc__node--dim');
    const lines = container.querySelectorAll('.gc__line');
    expect(lines[0]).not.toHaveClass('gc__line--dim');
    expect(lines[1]).toHaveClass('gc__line--dim');
  });

  /** § F/collaboration/graph/001428: Tab reaches one node, the arrow keys move to the nearest one. */
  it('has one tab stop and moves the focus with the arrow keys', async () => {
    const { cmp, button, fixture } = await setup({ nodes: [node('a'), node('b'), node('c')], lines: [] });
    expect(button('a')).toHaveAttribute('tabindex', '0');
    expect(button('b')).toHaveAttribute('tabindex', '-1');

    cmp.bodies.set([
      { id: 'a', x: 0, y: 0, vx: 0, vy: 0 },
      { id: 'b', x: 120, y: 0, vx: 0, vy: 0 },
      { id: 'c', x: 0, y: 150, vx: 0, vy: 0 },
    ]);
    fixture.detectChanges();
    button('a').focus();
    const right = new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true });
    button('a').dispatchEvent(right);
    fixture.detectChanges();
    expect(right.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(button('b'));
    expect(button('b')).toHaveAttribute('tabindex', '0');
    expect(button('a')).toHaveAttribute('tabindex', '-1');

    button('b').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    button('a').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    expect(document.activeElement).toBe(button('c'));
    button('c').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    expect(document.activeElement).toBe(button('a'));

    // No node further up, and a key that is no arrow: the focus stays.
    const up = new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true, cancelable: true });
    button('a').dispatchEvent(up);
    expect(up.defaultPrevented).toBe(true);
    const letter = new KeyboardEvent('keydown', { key: 'x', bubbles: true, cancelable: true });
    button('a').dispatchEvent(letter);
    expect(letter.defaultPrevented).toBe(false);
    expect(document.activeElement).toBe(button('a'));
  });

  it('puts the tab stop on the chosen node, and on the first one when the focused node left', async () => {
    const { cmp, button, fixture } = await setup({ selected: 'b' });
    expect(button('b')).toHaveAttribute('tabindex', '0');
    cmp.focused.set('zzz');
    fixture.componentRef.setInput('selected', null);
    fixture.detectChanges();
    expect(button('a')).toHaveAttribute('tabindex', '0');
    fixture.componentRef.setInput('nodes', []);
    fixture.detectChanges();
    expect(cmp.tabStop()).toBeNull();
  });

  /** § F/collaboration/graph/001429: a press on the empty drawing ends the choice, a drag moves the view. */
  it('ends the choice with a press on the empty drawing and moves the view with a drag', async () => {
    const { cmp, chosen, surface, button } = await setup();
    cmp.onDown(pointer(surface, 1, 100, 100));
    cmp.onMove(pointer(surface, 1, 102, 101, 'pointermove'));
    cmp.onUp(pointer(surface, 1, 102, 101, 'pointerup'));
    expect(chosen).toHaveBeenCalledWith(null);

    chosen.mockClear();
    const start = cmp.view();
    cmp.onDown(pointer(surface, 1, 100, 100));
    cmp.onMove(pointer(surface, 1, 160, 130, 'pointermove'));
    expect(cmp.view()).toEqual({ x: start.x + 60, y: start.y + 30, zoom: start.zoom });
    cmp.onUp(pointer(surface, 1, 160, 130, 'pointerup'));
    expect(chosen).not.toHaveBeenCalled();

    // A drag that starts on a node, a move of an unknown pointer and a cancelled press leave the view.
    cmp.onDown(pointer(button('a'), 2, 0, 0));
    cmp.onMove(pointer(surface, 2, 50, 50, 'pointermove'));
    cmp.onUp(pointer(surface, 2, 50, 50, 'pointerup'));
    cmp.onDown(pointer(surface, 3, 10, 10));
    cmp.onUp(pointer(surface, 3, 10, 10, 'pointercancel'));
    expect(chosen).not.toHaveBeenCalled();
    expect(cmp.view()).toEqual({ x: start.x + 60, y: start.y + 30, zoom: start.zoom });
  });

  /** § F/collaboration/graph/001433: a drag on a node moves the node, and it stays there. */
  it('moves a node with a drag and holds it where the person lets go', async () => {
    const { cmp, chosen, surface, button, fixture } = await setup();
    const capture = jest.fn();
    Object.defineProperty(surface, 'setPointerCapture', { value: capture, configurable: true });
    const view = cmp.view();
    const others = cmp.bodies().filter((b) => b.id !== 'a');

    cmp.onDown(pointer(button('a'), 1, 100, 100));
    // A second pointer on another node does not take over.
    cmp.onDown(pointer(button('b'), 2, 0, 0));
    cmp.onMove(pointer(surface, 1, 102, 101, 'pointermove'));
    expect(cmp.held()).toBeNull();
    expect(capture).not.toHaveBeenCalled();

    cmp.onMove(pointer(surface, 1, 200, 150, 'pointermove'));
    fixture.detectChanges();
    expect(cmp.held()).toBe('a');
    expect(capture).toHaveBeenCalledWith(1);
    expect(button('a')).toHaveClass('gc__node--held');
    const moved = cmp.bodies().find((b) => b.id === 'a');
    expect(moved?.fixed).toBe(true);
    expect(moved?.x).toBeCloseTo((200 - view.x) / view.zoom);
    expect(moved?.y).toBeCloseTo((150 - view.y) / view.zoom);
    // With reduced motion the other nodes stay, and the view stays too.
    expect(cmp.bodies().filter((b) => b.id !== 'a')).toEqual(others);
    expect(cmp.view()).toEqual(view);

    cmp.onUp(pointer(surface, 1, 200, 150, 'pointerup'));
    expect(cmp.held()).toBeNull();
    // The click that ends the drag is no press; the next one is.
    button('a').click();
    expect(chosen).not.toHaveBeenCalled();
    await new Promise((done) => setTimeout(done));
    button('a').click();
    expect(chosen).toHaveBeenCalledWith('a');
  });

  it('lets the neighbours follow a moved node unless nothing may move', async () => {
    const f = frames();
    const { cmp, surface, button } = await setup({ reduce: false, nodes: [node('a'), node('b')], lines: [line('a', 'b')] });
    f.run();
    cmp.onDown(pointer(button('a'), 1, 0, 0));
    cmp.onMove(pointer(surface, 1, 300, 300, 'pointermove'));
    expect(f.queue).toHaveLength(1);
    const held = cmp.bodies().find((b) => b.id === 'a');
    const before = cmp.bodies().find((b) => b.id === 'b');
    f.run();
    expect(cmp.bodies().find((b) => b.id === 'a')).toEqual(held);
    expect(cmp.bodies().find((b) => b.id === 'b')).not.toEqual(before);
    cmp.onUp(pointer(surface, 1, 300, 300, 'pointerup'));
  });

  /** § F/collaboration/graph/001433: Alt and an arrow key move the node without a pointer. */
  it('moves a node with Alt and an arrow key', async () => {
    const { cmp, button } = await setup();
    const at = cmp.bodies().find((b) => b.id === 'a') as Body;
    const press = (key: string): void => {
      button('a').dispatchEvent(new KeyboardEvent('keydown', { key, altKey: true, bubbles: true, cancelable: true }));
    };
    press('ArrowRight');
    press('ArrowDown');
    const there = cmp.bodies().find((b) => b.id === 'a') as Body;
    expect(there.fixed).toBe(true);
    expect(there.x).toBeCloseTo(at.x + NUDGE);
    expect(there.y).toBeCloseTo(at.y + NUDGE);
    press('ArrowLeft');
    press('ArrowUp');
    const back = cmp.bodies().find((b) => b.id === 'a') as Body;
    expect(back.x).toBeCloseTo(at.x);
    expect(back.y).toBeCloseTo(at.y);
    expect(document.activeElement).not.toBe(button('b'));
  });

  it('captures the pointer of a drag', async () => {
    const { cmp, surface } = await setup();
    const capture = jest.fn();
    Object.defineProperty(surface, 'setPointerCapture', { value: capture, configurable: true });
    cmp.onDown(pointer(surface, 7, 0, 0));
    expect(capture).toHaveBeenCalledWith(7);
  });

  it('leaves the edge at the top and at the foot free when it fits the drawing', async () => {
    const { cmp, fixture } = await setup();
    const fitted = cmp.view();
    fixture.componentRef.setInput('edge', 250);
    screen.getByRole('button', { name: 'Alles zeigen' }).click();
    expect(cmp.view().zoom).toBeLessThan(fitted.zoom);
  });

  it('zooms with a pinch, the wheel and the buttons, and fits the drawing again', async () => {
    const { cmp, surface, fixture, container } = await setup();
    const fitted = cmp.view();

    cmp.onDown(pointer(surface, 1, 100, 100));
    cmp.onDown(pointer(surface, 2, 200, 100));
    cmp.onMove(pointer(surface, 2, 300, 100, 'pointermove'));
    expect(cmp.view().zoom).toBeCloseTo(fitted.zoom * 2);
    cmp.onUp(pointer(surface, 1, 100, 100, 'pointerup'));
    cmp.onUp(pointer(surface, 2, 300, 100, 'pointerup'));

    const prevent = jest.fn();
    const zoomed = cmp.view().zoom;
    cmp.onWheel({ deltaY: 200, clientX: 400, clientY: 300, preventDefault: prevent } as unknown as WheelEvent);
    expect(prevent).toHaveBeenCalled();
    expect(cmp.view().zoom).toBeLessThan(zoomed);

    screen.getByRole('button', { name: 'Alles zeigen' }).click();
    expect(cmp.view()).toEqual(fitted);
    screen.getByRole('button', { name: 'Vergrößern' }).click();
    expect(cmp.view().zoom).toBeGreaterThan(fitted.zoom);
    screen.getByRole('button', { name: 'Alles zeigen' }).click();
    screen.getByRole('button', { name: 'Verkleinern' }).click();
    screen.getByRole('button', { name: 'Verkleinern' }).click();
    fixture.detectChanges();
    expect(cmp.view().zoom).toBeLessThan(LABEL_ZOOM);
    // § 001430: the titles hide when they are too small to read.
    expect(container.querySelector('.gc')).not.toHaveClass('gc--labels');
    expect(screen.getByRole('group', { name: 'Ansicht der Zeichnung' })).toBeInTheDocument();
  });

  it('stops following the drawing after the person moved the view, until the drawing is empty', async () => {
    const { cmp, fixture } = await setup();
    cmp.zoomOut();
    const own = cmp.view();
    fixture.componentRef.setInput('nodes', [...NODES, node('d')]);
    fixture.detectChanges();
    expect(cmp.view()).toEqual(own);

    fixture.componentRef.setInput('nodes', []);
    fixture.componentRef.setInput('lines', []);
    fixture.detectChanges();
    expect(cmp.bodies()).toEqual([]);
    expect(cmp.view()).toEqual({ x: 400, y: 300, zoom: 1 });
  });

  it('moves the view to a chosen node outside the frame', async () => {
    const { cmp, fixture } = await setup();
    cmp.bodies.set([
      { id: 'a', x: 0, y: 0, vx: 0, vy: 0 },
      { id: 'b', x: 5000, y: 0, vx: 0, vy: 0 },
      { id: 'c', x: 0, y: 40, vx: 0, vy: 0 },
    ]);
    cmp.view.set({ x: 400, y: 300, zoom: 1 });
    fixture.componentRef.setInput('selected', 'a');
    fixture.detectChanges();
    expect(cmp.view()).toEqual({ x: 400, y: 300, zoom: 1 });
    fixture.componentRef.setInput('selected', 'b');
    fixture.detectChanges();
    expect(cmp.view()).toEqual({ x: 400 - 5000, y: 300, zoom: 1 });
    fixture.componentRef.setInput('selected', 'gone');
    fixture.detectChanges();
    expect(cmp.view()).toEqual({ x: 400 - 5000, y: 300, zoom: 1 });
    expect(cmp.at('gone')).toBe('translate(0px, 0px)');
  });

  it('goes to 1:1 on a chosen node when the titles are too small to show', async () => {
    const { cmp, fixture, container } = await setup();
    cmp.bodies.set([
      { id: 'a', x: 100, y: 50, vx: 0, vy: 0 },
      { id: 'b', x: 900, y: 0, vx: 0, vy: 0 },
      { id: 'c', x: 0, y: 40, vx: 0, vy: 0 },
    ]);
    cmp.view.set({ x: 400, y: 300, zoom: 0.5 });
    fixture.componentRef.setInput('selected', 'a');
    fixture.detectChanges();
    expect(cmp.view()).toEqual({ x: 300, y: 250, zoom: 1 });

    // The page moves the place of a chosen node away from its panel.
    fixture.componentRef.setInput('focusAt', { x: 0.25, y: 0.5 });
    cmp.view.set({ x: 0, y: 0, zoom: 0.5 });
    fixture.componentRef.setInput('selected', 'b');
    fixture.detectChanges();
    expect(cmp.view()).toEqual({ x: 200 - 900, y: 300, zoom: 1 });
    fixture.componentRef.setInput('selected', 'c');
    cmp.view.set({ x: 5000, y: 0, zoom: 1 });
    fixture.componentRef.setInput('selected', 'a');
    fixture.detectChanges();
    expect(cmp.view()).toEqual({ x: 200 - 100, y: 300 - 50, zoom: 1 });
    expect((container.querySelector('.gc') as HTMLElement).style.getPropertyValue('--gc-zoom')).toBe('1');
  });

  it('measures the frame again when its size changes', async () => {
    const observed: ResizeObserverCallback[] = [];
    const Original = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class {
      constructor(cb: ResizeObserverCallback) {
        observed.push(cb);
      }
      readonly observe = jest.fn();
      readonly unobserve = jest.fn();
      readonly disconnect = jest.fn();
    } as unknown as typeof ResizeObserver;
    try {
      const { cmp } = await setup();
      expect(cmp.size()).toEqual({ width: 800, height: 600 });
      width.mockReturnValue(400);
      observed.forEach((cb) => cb([], {} as ResizeObserver));
      expect(cmp.size()).toEqual({ width: 400, height: 600 });
    } finally {
      globalThis.ResizeObserver = Original;
    }
  });
});
