/**
 * Style contract of the head of the group "Darstellung" (§000608). jsdom does no layout, so
 * this spec reads the styles: the head row has the inline padding of the switch rows, so the
 * reset ends where the switch tracks end, and the caption has no padding of its own, so its
 * text and the reset share one centre line.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const css = readFileSync(join(__dirname, 'help-menu.component.scss'), 'utf8');

/** The declarations of the first rule with exactly this selector. */
function rule(selector: string): string {
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = css.match(new RegExp(`(?:^|\\n)${esc} \\{([^}]*)\\}`));
  if (!m) throw new Error(`No rule ${selector}`);
  return m[1];
}

describe('HelpMenuStyles', () => {
  /** §000608 the reset lines up with the switches and the caption, in the popover and the sheet. */
  it('aligns the reset with the switch column and the caption', () => {
    expect(rule('.hm__toggle')).toMatch(/padding: 6px var\(--space-4\);/);
    const head = rule('.hm__groupHead');
    expect(head).toMatch(/align-items: center;/);
    expect(head).toMatch(/padding: 4px var\(--space-4\) 0;/);
    expect(rule('.hm__groupHead > .hm__group')).toMatch(/padding: 0;/);
    expect(rule('.hm--sheet .hm__group,\n.hm--sheet .hm__toggle')).toMatch(/padding-inline: var\(--space-2\);/);
    expect(rule('.hm--sheet .hm__groupHead')).toMatch(/padding-inline: var\(--space-2\);/);
    expect(rule('.hm__reset')).not.toMatch(/margin: (?!0;)/);
  });
});
