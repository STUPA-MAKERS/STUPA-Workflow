/**
 * The measures of very high contrast (§ NF/accessibility/settings/000614 and 000621), run in
 * the page. jsdom computes no colours, so only a real browser can take them.
 *
 * - `noYellow`: a control that a person can press and that shows no yellow, neither as its
 *   fill, its edge or its text, nor on a part inside it. A destructive row in the light red
 *   of the mode is allowed (000617).
 * - `lowOnYellow`: a text on a yellow fill with a contrast below 7:1.
 */
export interface YellowReport {
  noYellow: string[];
  lowOnYellow: string[];
}

export function measureYellow(): YellowReport {
  type Rgb = { r: number; g: number; b: number; a: number };
  const CONTROLS =
    'button, a[href], input, select, textarea, summary, [role=button], [role=tab], [role=checkbox], ' +
    '[role=switch], [role=radio], [role=menuitem], [role=menuitemradio], [role=menuitemcheckbox], ' +
    '[role=option], [role=combobox], [role=link], tr.dt__row--clickable';
  const rgb = (value: string): Rgb | null => {
    const m = value.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p[3] === undefined ? 1 : p[3] };
  };
  const yellow = (c: Rgb | null): boolean => !!c && c.a > 0.5 && c.r > 240 && c.g > 240 && c.b < 40;
  const lightRed = (c: Rgb | null): boolean => !!c && c.r > 240 && c.g > 120 && c.g < 150 && c.b > 120 && c.b < 150;
  const anyYellow = (value: string): boolean => (value.match(/rgba?\([^)]+\)/g) ?? []).some((m) => yellow(rgb(m)));
  const fill = (el: Element): Rgb => {
    for (let e: Element | null = el; e; e = e.parentElement) {
      const c = rgb(getComputedStyle(e).backgroundColor);
      if (c && c.a > 0.5) return c;
    }
    return { r: 0, g: 0, b: 0, a: 1 };
  };
  const luminance = (c: Rgb): number => {
    const f = (v: number): number => (v / 255 <= 0.03928 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const ratio = (a: Rgb, b: Rgb): number => {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  };
  const visible = (el: Element): boolean => {
    const box = el.getBoundingClientRect();
    return box.width >= 4 && box.height >= 4 && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
  };
  const name = (el: Element): string =>
    `${el.tagName.toLowerCase()}.${(el.getAttribute('class') ?? '').replace(/ng-[\w-]+/g, '').trim().split(/\s+/).slice(0, 3).join('.')}`;

  const noYellow = [...document.querySelectorAll<HTMLElement>(CONTROLS)]
    .filter((el) => {
      if (!visible(el) || el.matches(':disabled, [aria-disabled="true"]') || el.closest('[inert]')) return false;
      const cs = getComputedStyle(el);
      if (lightRed(rgb(cs.color))) return false;
      const own =
        yellow(rgb(cs.color)) ||
        yellow(fill(el)) ||
        (cs.outlineStyle !== 'none' && yellow(rgb(cs.outlineColor))) ||
        (cs.borderTopStyle !== 'none' && cs.borderTopWidth !== '0px' && yellow(rgb(cs.borderTopColor))) ||
        anyYellow(cs.boxShadow);
      if (own) return false;
      return ![...el.querySelectorAll<HTMLElement>('*')].some((part) => {
        if (!visible(part)) return false;
        const ps = getComputedStyle(part);
        return (yellow(rgb(ps.color)) && part.innerText.trim() !== '') || yellow(rgb(ps.backgroundColor));
      });
    })
    .map(name);

  const lowOnYellow: string[] = [];
  const seen = new Set<Element>();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const el = walker.currentNode.parentElement;
    if (!walker.currentNode.nodeValue?.trim() || !el || seen.has(el) || !visible(el)) continue;
    seen.add(el);
    const on = fill(el);
    const colour = rgb(getComputedStyle(el).color);
    if (yellow(on) && colour && ratio(colour, on) < 7) lowOnYellow.push(name(el));
  }
  return { noYellow: [...new Set(noYellow)], lowOnYellow: [...new Set(lowOnYellow)] };
}
