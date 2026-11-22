/**
 * The measure of §ui-kit:NF/usability/layout/002420, run in the page: every bar and head that
 * sticks over scrolling content is opaque in every state, also before the page script has
 * noted that content is under it.
 *
 * A browser moves a fast scroll on its own thread, and the script that sets the stuck or
 * scrolled class of a bar runs one frame or more later. A colour that only such a class gives
 * shows the rows through the bar in those frames. The measure so strips every state class
 * (`…--stuck`, `…--scrolled`, `…--under`, `…--condensed`) and reads each sticky element as wide
 * as most of the screen, then puts the classes back and reads again. jsdom computes no
 * colours, so only a real browser can take it.
 */
export interface OpaqueHeadReport {
  /** The sticky bars of the page that were read. */
  bars: number;
  /** A bar that lets the content under it show through, with the state it was read in. */
  seeThrough: string[];
}

export function measureOpaqueHeads(): OpaqueHeadReport {
  const STATE = /--(stuck|scrolled|under|condensed)$/;
  const alpha = (value: string): number => {
    if (value === 'transparent') return 0;
    const m = value.match(/rgba?\(([^)]+)\)/) ?? value.match(/color\([^ ]+ ([^)]+)\)/);
    if (!m) return 1;
    const parts = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    return parts[3] === undefined ? 1 : parts[3];
  };
  const name = (el: Element): string =>
    el.tagName.toLowerCase() + Array.from(el.classList).map((c) => `.${c}`).join('');
  const bars = Array.from(document.querySelectorAll<HTMLElement>('body *')).filter((el) => {
    const style = getComputedStyle(el);
    if (style.position !== 'sticky' || style.display === 'contents') return false;
    const box = el.getBoundingClientRect();
    return box.height > 0 && box.width >= window.innerWidth * 0.9;
  });
  const read = (state: string): string[] =>
    bars.filter((el) => alpha(getComputedStyle(el).backgroundColor) < 1).map((el) => `${name(el)} (${state})`);

  const stripped = Array.from(document.querySelectorAll('[class*="--"]')).flatMap((el) =>
    Array.from(el.classList)
      .filter((c) => STATE.test(c))
      .map((c) => ({ el, c })),
  );
  for (const { el, c } of stripped) el.classList.remove(c);
  const atRest = read('before the script notes the scroll');
  for (const { el, c } of stripped) el.classList.add(c);
  const settled = read('settled');
  return { bars: bars.length, seeThrough: [...atRest, ...settled] };
}
