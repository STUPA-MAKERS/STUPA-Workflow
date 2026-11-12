/**
 * Spec 000741: a button that loads more rows of a list is centred and has a chevron. jsdom
 * applies no styles and the icon shows no name in the DOM, so this spec reads the sources.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const FEATURES = join(__dirname, '../features');
const LISTS = ['calendar/calendar.component', 'meetings/meetings-list/meetings-list.component'];

/** The icon names of the load buttons of a template, in the order of the template. */
function loadIcons(html: string): readonly string[] {
  return [...html.matchAll(/class="[a-z-]+__more"[^]*?<app-icon name="([a-z-]+)"/g)].map((m) => m[1]);
}

describe('loadMoreButtons (§000741)', () => {
  it('every load button of the Kalender and of the Sitzungen has a chevron', () => {
    const [calendar, meetings] = LISTS.map((path) => loadIcons(readFileSync(join(FEATURES, `${path}.html`), 'utf8')));
    expect(calendar).toEqual(['up', 'down']);
    expect(meetings).toEqual(['down', 'down', 'down']);
  });

  it('no load button leaves the centre of its list', () => {
    const styles = LISTS.map((path) => readFileSync(join(FEATURES, `${path}.scss`), 'utf8'));
    styles.forEach((scss) => expect(scss).not.toMatch(/__more--/));
  });
});
