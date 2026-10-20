/**
 * The phone composer of a card sits at the foot of the activity sheet.
 *
 * On a phone the activity opens in a sheet from the bottom, in the board drawer and in the
 * pane of "Aufgaben". The sheet lies over the bottom navigation, so its composer takes no
 * offset for the navigation (`--chat-composer-bottom: 0px`). The chat of the wide columns
 * keeps the default offset of the chat.
 *
 * jsdom applies no styles, so this spec reads the source: only the chat of the sheet sets
 * `--chat-composer-bottom`.
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
  it('sets the zero composer offset only on the chat of the activity sheet', () => {
    expect(selectorsSetting(SCSS, '--chat-composer-bottom')).toEqual(['.cd__chat--sheet']);
  });
});
