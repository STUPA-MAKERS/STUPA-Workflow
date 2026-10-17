/**
 * The phone composer of a card sits above the bottom navigation.
 *
 * In the drawer of the board the drawer ends on the bottom navigation, so the composer bar
 * sits at the foot of the drawer (`--chat-composer-bottom: 0px`). In the pane of
 * "Aufgaben" (`mode="pane"`) the page scrolls under the navigation, and the same offset put
 * the composer under the navigation. There the chat keeps its default offset
 * (`--app-bottom-inset`).
 *
 * jsdom applies no styles, so this spec reads the source: every rule of the card detail
 * that sets `--chat-composer-bottom` must leave out the pane.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const SCSS = readFileSync(join(__dirname, 'todo-card-detail.component.scss'), 'utf8');

/** The selectors of the rules whose body sets `prop`. */
function selectorsSetting(css: string, prop: string): string[] {
  const out: string[] = [];
  const rule = /([^{}]+)\{([^{}]*)\}/g;
  for (let m = rule.exec(css); m; m = rule.exec(css)) {
    if (m[2]!.includes(`${prop}:`)) {
      out.push(m[1]!.replace(/\/\*[\s\S]*?\*\//g, '').trim());
    }
  }
  return out;
}

describe('card detail: phone composer offset', () => {
  it('sets the zero composer offset only outside the pane of Aufgaben', () => {
    const selectors = selectorsSetting(SCSS, '--chat-composer-bottom');
    expect(selectors.length).toBeGreaterThan(0);
    for (const selector of selectors) {
      expect(selector).toContain(':not(.cd--pane)');
    }
  });
});
