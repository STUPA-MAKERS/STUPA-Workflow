/**
 * Style contract of the chat log. jsdom does no layout, so this spec reads the styles:
 * the edit and delete pill stays inside the bubble's width, and the log never scrolls
 * sideways.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const css = readFileSync(join(__dirname, 'chat.component.scss'), 'utf8');

/** The declarations of the first rule with exactly this selector. */
function rule(selector: string): string {
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = css.match(new RegExp(`(?:^|\\n)${esc} \\{([^}]*)\\}`));
  if (!m) throw new Error(`No rule ${selector}`);
  return m[1];
}

describe('chat styles', () => {
  it('puts the actions over the bubble, not beside it', () => {
    const acts = rule('.chat__acts');
    expect(acts).toMatch(/position: absolute;/);
    expect(acts).toMatch(/inset-block-start: -16px;/);
    expect(acts).toMatch(/inset-inline-end: 0;/);
    // Nothing places the pill outside the bubble's box.
    expect(css).not.toMatch(/(right|left): calc\(100% \+/);
    const other = rule('.chat__row:not(.chat__row--own) .chat__acts');
    expect(other).toMatch(/inset-inline-end: auto;/);
    expect(other).toMatch(/inset-inline-start: 0;/);
  });

  it('lets the minimum of the phone log yield to a short viewport (open keyboard)', () => {
    expect(rule(':host(.chat--phone) .chat__log')).toMatch(
      /min-height: min\(var\(--chat-log-min, 10rem\), 25dvh\);/,
    );
  });

  it('scrolls the phone log right up to the rule of the composer', () => {
    expect(rule(':host(.chat--phone)')).toMatch(/gap: 0;/);
    expect(rule(':host(.chat--phone) .chat__log')).toMatch(
      /padding: var\(--chat-log-inset-top, 4px\) 0 calc\(12px \+ var\(--space-3\)\);/,
    );
  });

  it('cuts the phone log at its edge and never fades it', () => {
    expect(css).not.toMatch(/mask-image/);
  });

  it('never scrolls the log sideways', () => {
    expect(rule('.chat__log')).toMatch(/overflow-x: hidden;/);
  });
});
