/**
 * Touch events for the gesture specs. jsdom has no `Touch` constructor, so a plain event
 * carries the touch list and the time stamp of the move.
 */
export function touch(
  target: EventTarget,
  type: 'touchstart' | 'touchmove' | 'touchend' | 'touchcancel',
  points: readonly { x: number; y: number }[],
  timeStamp = 0,
): Event {
  const event = new Event(type, { bubbles: true, cancelable: true });
  const list = points.map((p) => ({ clientX: p.x, clientY: p.y }));
  Object.defineProperty(event, 'touches', { value: type === 'touchend' ? [] : list });
  Object.defineProperty(event, 'timeStamp', { value: timeStamp });
  target.dispatchEvent(event);
  return event;
}

/** A drag from `from` along `steps` (each `dt` ms apart), with the release at the end. */
export function drag(
  target: EventTarget,
  from: { x: number; y: number },
  steps: readonly { x: number; y: number }[],
  { dt = 16, release = true }: { dt?: number; release?: boolean } = {},
): Event[] {
  const moves: Event[] = [];
  touch(target, 'touchstart', [from], 0);
  steps.forEach((p, i) => moves.push(touch(target, 'touchmove', [p], (i + 1) * dt)));
  if (release) touch(target, 'touchend', [], (steps.length + 1) * dt);
  return moves;
}

/**
 * A `matchMedia` where the queries in `on` match. The phone and the coarse pointer turn
 * the gestures on.
 */
export function mediaMatching(on: readonly string[]): jest.SpyInstance {
  return jest.spyOn(window, 'matchMedia').mockImplementation(
    (query: string) =>
      ({
        matches: on.includes(query),
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      }) as unknown as MediaQueryList,
  );
}
