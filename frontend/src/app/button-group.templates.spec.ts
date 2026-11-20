/**
 * Button group contract of the app templates (spec 001354). jsdom renders no layout, so this
 * spec reads the HTML. Every button of the app (`app-button`, `a[appButton]`,
 * `button[appButton]`, `app-row-menu`) stands in a button group: in `app-button-group`, in an
 * element with the class `btn-grp`, or in a slot that the kit draws as a group (the actions of
 * `app-sheet-bar`, `app-page-header`, the bar of the list/detail layout, the footer of
 * `app-dialog`, the head of `app-side-sheet` and the head of a meeting). A single button
 * stands in a group of one.
 *
 * The chrome of the shell (rail, bottom bar, account menu) is not an action row, so its slots
 * are left out. A component whose host is a segment of the group of its parent
 * (`btn-grp__seg` on the host) draws its button at the root of its template.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const SRC = join(__dirname, '..');

/** The slots that the kit draws as a group. */
const GROUP_SLOTS = ['dialog-footer', 'sheet-actions', 'actions'];
/** The elements whose content the kit draws as a group. */
const GROUP_TAGS = ['app-button-group', 'app-sheet-bar', 'app-list-detail-bar'];
/**
 * The elements whose content stands in a group: the head of a meeting, and an `ng-container`
 * marked `btnGrpContent` in a template that a group renders (the dock tools of a page).
 */
const GROUP_ATTRS = ['appmeetinghead', 'btngrpcontent'];
/** The slots of the shell chrome, which hold navigation and not actions. */
const CHROME_SLOTS = [
  'accountitems',
  'barend',
  'more',
  'moreaccount',
  'railaccount',
  'railend',
  'railtools',
  'shellaccount',
  'shellbarend',
  'shellfooter',
  'shellmain',
  'shellmore',
  'shelloverlays',
  'shellprompts',
  'shellpublicheader',
  'shellrailend',
  'shellrailtools',
];
/** The templates whose host is a segment of the group of the parent (`btn-grp__seg`). */
const SEGMENT_HOSTS = [
  'app/features/meetings/protocol-bar/protocol-bar.component.html',
  'app/features/meetings/public-join/join-qr.component.html',
];
const VOID = new Set(['input', 'img', 'br', 'hr', 'meta', 'link', 'source', 'col', 'area', 'wbr']);

interface Tag {
  readonly name: string;
  readonly attrs: string;
}

function htmlFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return htmlFiles(path);
    return name.endsWith('.html') ? [path] : [];
  });
}

const attrNames = (attrs: string): string[] =>
  Array.from(attrs.matchAll(/(?:^|\s)([^\s=/]+)(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?/g)).map(
    (m) => m[1].toLowerCase(),
  );

const isButton = (tag: Tag): boolean =>
  tag.name === 'app-button' ||
  tag.name === 'app-row-menu' ||
  ((tag.name === 'a' || tag.name === 'button') && attrNames(tag.attrs).includes('appbutton'));

const isGroup = (tag: Tag): boolean => {
  const names = attrNames(tag.attrs);
  const projectAs = /ngProjectAs="\[([^\]]+)\]"/i.exec(tag.attrs)?.[1] ?? '';
  return (
    GROUP_TAGS.includes(tag.name) ||
    /class="[^"]*\bbtn-grp\b/.test(tag.attrs) ||
    names.some(
      (n) => GROUP_SLOTS.includes(n) || CHROME_SLOTS.includes(n) || GROUP_ATTRS.includes(n),
    ) ||
    GROUP_SLOTS.includes(projectAs)
  );
};

/** The line of each button of `source` that stands outside a group. */
export function loneButtons(source: string): readonly number[] {
  const text = source.replace(/<!--[\s\S]*?-->/g, (c) => c.replace(/[^\n]/g, ' '));
  const tags = Array.from(
    text.matchAll(/<(\/?)([a-zA-Z][\w-]*)((?:"[^"]*"|'[^']*'|[^'">])*?)(\/?)>/g),
  );
  return tags.reduce<{ stack: readonly Tag[]; found: readonly number[] }>(
    (acc, m) => {
      const name = m[2].toLowerCase();
      if (m[1]) {
        const at = acc.stack.map((t) => t.name).lastIndexOf(name);
        return at < 0 ? acc : { ...acc, stack: acc.stack.slice(0, at) };
      }
      const tag: Tag = { name, attrs: m[3] };
      const lone = isButton(tag) && !isGroup(tag) && !acc.stack.some(isGroup);
      const found = lone ? [...acc.found, text.slice(0, m.index).split('\n').length] : acc.found;
      const closed = Boolean(m[4]) || VOID.has(name);
      return { stack: closed ? acc.stack : [...acc.stack, tag], found };
    },
    { stack: [], found: [] },
  ).found;
}

describe('ButtonGroupTemplates', () => {
  it('finds a lone button and passes a button in a group or a group slot', () => {
    expect(loneButtons('<div>\n<app-button>A</app-button></div>')).toEqual([2]);
    expect(loneButtons('<app-button-group><app-button>A</app-button></app-button-group>')).toEqual(
      [],
    );
    expect(loneButtons('<span class="x btn-grp"><a appButton>A</a></span>')).toEqual([]);
    expect(
      loneButtons('<app-dialog><app-button dialog-footer>A</app-button></app-dialog>'),
    ).toEqual([]);
    expect(
      loneButtons('<ng-container ngProjectAs="[actions]"><app-row-menu /></ng-container>'),
    ).toEqual([]);
    expect(loneButtons('<!-- <app-button>A</app-button> -->')).toEqual([]);
    expect(
      loneButtons('<ng-container btnGrpContent><app-button>A</app-button></ng-container>'),
    ).toEqual([]);
  });

  it('puts every button of the app in a button group (001354)', () => {
    const offenders = htmlFiles(join(SRC, 'app'))
      .filter((path) => !SEGMENT_HOSTS.includes(relative(SRC, path)))
      .flatMap((path) =>
        loneButtons(readFileSync(path, 'utf8')).map((line) => `${relative(SRC, path)}:${line}`),
      );
    expect(offenders).toEqual([]);
  });
});
