import {
  ALPHA_MIN,
  ALPHA_START,
  type Body,
  LINK_LENGTH,
  SETTLE_STEPS,
  ZOOM_MAX,
  ZOOM_MIN,
  adjacency,
  bounds,
  clampZoom,
  fit,
  hashUnit,
  hold,
  keep,
  nearestIn,
  place,
  settle,
  step,
  zoomAt,
} from './graph-layout';

const body = (id: string, x: number, y: number): Body => ({ id, x, y, vx: 0, vy: 0 });
const distance = (a: Body, b: Body): number => Math.hypot(a.x - b.x, a.y - b.y);
const find = (bodies: readonly Body[], id: string): Body => bodies.find((b) => b.id === id) as Body;

describe('graph layout', () => {
  it('hashes a text to a stable number from 0 to 1', () => {
    expect(hashUnit('meeting:1')).toBe(hashUnit('meeting:1'));
    expect(hashUnit('meeting:1')).not.toBe(hashUnit('meeting:1', 1));
    for (const text of ['', 'a', 'todo:42', 'ä'.repeat(40)]) {
      expect(hashUnit(text)).toBeGreaterThanOrEqual(0);
      expect(hashUnit(text)).toBeLessThan(1);
    }
  });

  it('lists the ids that each node connects to', () => {
    const near = adjacency([
      { a: 'a', b: 'b' },
      { a: 'c', b: 'a' },
    ]);
    expect(near.get('a')).toEqual(['b', 'c']);
    expect(near.get('b')).toEqual(['a']);
    expect(near.get('c')).toEqual(['a']);
    expect(near.get('d')).toBeUndefined();
  });

  /** § F/collaboration/graph/001426: a new node appears next to a neighbour that already shows. */
  it('places a new node beside a neighbour and keeps the bodies that exist', () => {
    const old = body('a', 400, -300);
    const placed = place([old], ['a', 'b', 'c'], adjacency([{ a: 'a', b: 'b' }]));
    expect(placed[0]).toBe(old);
    expect(placed.map((b) => b.id)).toEqual(['a', 'b', 'c']);
    expect(distance(find(placed, 'b'), old)).toBeLessThan(LINK_LENGTH);
    expect(distance(find(placed, 'b'), old)).toBeGreaterThan(LINK_LENGTH * 0.4);
    // No neighbour: on a ring around the origin.
    expect(Math.hypot(find(placed, 'c').x, find(placed, 'c').y)).toBeCloseTo(LINK_LENGTH * (1 + Math.sqrt(2)));
  });

  it('places a node whose neighbour has no place yet on the ring', () => {
    const placed = place([], ['a', 'b'], adjacency([{ a: 'a', b: 'b' }]));
    expect(Math.hypot(placed[0].x, placed[0].y)).toBeCloseTo(LINK_LENGTH);
    expect(distance(placed[0], placed[1])).toBeLessThan(LINK_LENGTH);
  });

  it('keeps only the bodies of the ids', () => {
    expect(keep([body('a', 0, 0), body('b', 1, 1)], new Set(['b'])).map((b) => b.id)).toEqual(['b']);
  });

  it('pulls two linked nodes together and pushes two close nodes apart', () => {
    const near = adjacency([{ a: 'a', b: 'b' }]);
    const far = [body('a', -300, 0), body('b', 300, 0)];
    const pulled = step(far, near, 1);
    expect(distance(pulled[0], pulled[1])).toBeLessThan(600);

    const close = [body('a', -5, 0), body('b', 5, 0)];
    const pushed = step(close, new Map(), 1);
    expect(distance(pushed[0], pushed[1])).toBeGreaterThan(10);
  });

  it('separates two nodes at one place and ignores a line to a missing node', () => {
    const moved = step([body('a', 0, 0), body('b', 0, 0)], adjacency([{ a: 'a', b: 'gone' }]), 1);
    expect(distance(moved[0], moved[1])).toBeGreaterThan(0);
  });

  it('limits the speed of a node', () => {
    const moved = step([body('a', 0, 0), body('b', 100000, 0)], adjacency([{ a: 'a', b: 'b' }]), 1);
    expect(Math.abs(moved[0].vx)).toBeLessThanOrEqual(42);
  });

  /** § F/collaboration/graph/001427: the layout runs to its end in one go. */
  it('settles to a layout at rest with the lines near their length', () => {
    const near = adjacency([{ a: 'a', b: 'b' }]);
    const rested = settle(place([], ['a', 'b'], near), near);
    expect(rested.every((b) => b.vx === 0 && b.vy === 0)).toBe(true);
    expect(distance(rested[0], rested[1])).toBeGreaterThan(LINK_LENGTH * 0.5);
    expect(distance(rested[0], rested[1])).toBeLessThan(LINK_LENGTH * 3);
    expect(SETTLE_STEPS).toBeGreaterThan(10);
    expect(ALPHA_MIN).toBeLessThan(ALPHA_START);
  });

  /** § F/collaboration/graph/001433: a node that the person put somewhere stays there. */
  it('holds a node at its place while the others move', () => {
    const bodies = hold([body('a', 0, 0), body('b', 5, 0)], 'a', 40, 30);
    expect(find(bodies, 'a')).toEqual({ id: 'a', x: 40, y: 30, vx: 0, vy: 0, fixed: true });
    expect(find(bodies, 'b')).toEqual(body('b', 5, 0));
    const after = settle(bodies, adjacency([{ a: 'a', b: 'b' }]));
    expect(find(after, 'a')).toEqual({ id: 'a', x: 40, y: 30, vx: 0, vy: 0, fixed: true });
    expect(find(after, 'b')).not.toEqual(body('b', 5, 0));
    expect(Math.abs(distance(find(after, 'a'), find(after, 'b')) - LINK_LENGTH)).toBeLessThan(LINK_LENGTH);
  });

  it('only stops the nodes when alpha is below the rest value', () => {
    const moving: Body = { id: 'a', x: 3, y: 4, vx: 9, vy: 9 };
    expect(settle([moving], new Map(), 0)).toEqual([{ id: 'a', x: 3, y: 4, vx: 0, vy: 0 }]);
  });

  it('gives the box around the bodies', () => {
    expect(bounds([])).toBeNull();
    expect(bounds([body('a', -10, 5), body('b', 30, -20)], 4)).toEqual({ minX: -14, minY: -24, maxX: 34, maxY: 9 });
    expect(bounds([body('a', 1, 2)])).toEqual({ minX: 1, minY: 2, maxX: 1, maxY: 2 });
  });

  it('fits a box into the frame, never larger than 1:1', () => {
    expect(fit(null, 800, 600)).toEqual({ x: 400, y: 300, zoom: 1 });
    expect(fit({ minX: 0, minY: 0, maxX: 10, maxY: 10 }, 0, 0)).toEqual({ x: 0, y: 0, zoom: 1 });
    expect(fit({ minX: -50, minY: -50, maxX: 50, maxY: 50 }, 800, 600)).toEqual({ x: 400, y: 300, zoom: 1 });
    const wide = fit({ minX: 0, minY: 0, maxX: 1600, maxY: 600 }, 800, 600);
    expect(wide.zoom).toBe(0.5);
    expect(wide.x).toBe(0);
    expect(wide.y).toBe(150);
    expect(fit({ minX: 0, minY: 0, maxX: 1e6, maxY: 1 }, 800, 600).zoom).toBe(ZOOM_MIN);
  });

  it('zooms around a point of the frame and stays in the zoom range', () => {
    const view = zoomAt({ x: 100, y: 50, zoom: 1 }, 2, 300, 200);
    expect(view.zoom).toBe(2);
    // The point (300, 200) shows the same place of the layout.
    expect((300 - view.x) / view.zoom).toBe(300 - 100);
    expect((200 - view.y) / view.zoom).toBe(200 - 50);
    expect(zoomAt({ x: 0, y: 0, zoom: 2 }, 100, 0, 0).zoom).toBe(ZOOM_MAX);
    expect(clampZoom(0)).toBe(ZOOM_MIN);
    expect(clampZoom(1)).toBe(1);
  });

  /** § F/collaboration/graph/001428: the arrow keys move to the nearest node in that direction. */
  it('finds the nearest node in a direction', () => {
    const bodies = [
      body('mid', 0, 0),
      body('right', 100, 10),
      body('far-right', 300, 0),
      body('left', -80, -10),
      body('up', 5, -90),
      body('down', -5, 120),
    ];
    expect(nearestIn(bodies, 'mid', 'right')).toBe('right');
    expect(nearestIn(bodies, 'mid', 'left')).toBe('left');
    expect(nearestIn(bodies, 'mid', 'up')).toBe('up');
    expect(nearestIn(bodies, 'mid', 'down')).toBe('down');
    expect(nearestIn(bodies, 'far-right', 'right')).toBeNull();
    expect(nearestIn(bodies, 'gone', 'right')).toBe('mid');
    expect(nearestIn([], 'gone', 'up')).toBeNull();
  });
});
