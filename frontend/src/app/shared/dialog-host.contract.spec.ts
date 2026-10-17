/**
 * An open dialog changes nothing in the layout of the page that holds it.
 *
 * The backdrop of `app-dialog` is fixed, but the host element was an inline box. In a flex
 * column (the meeting page) an open dialog became a flex item of zero height and took one
 * gap, so the dock below the agenda rose by 24px while "TOP hinzufügen" was open. The
 * global stylesheet gives the host no box.
 *
 * jsdom applies no styles, so this spec reads the source.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const GLOBAL_STYLES = join(__dirname, '../../styles.scss');

describe('app-dialog host (contract)', () => {
  it('adds no box in the page, open or closed', () => {
    const scss = readFileSync(GLOBAL_STYLES, 'utf8');
    expect(scss).toMatch(/^app-dialog\s*\{\s*display:\s*contents;\s*\}/m);
  });
});
