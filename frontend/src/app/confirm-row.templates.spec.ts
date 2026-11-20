/**
 * Confirm row contract of the app templates (spec 001960). jsdom renders no layout, so this
 * spec reads the HTML. The action group at the end of a dialog, a sheet, a popover or an
 * inline form is a confirm row: the footer of `app-dialog` (`dialog-footer`) or an
 * `app-button-group` with `[main]="true"`. The kit gives every button of a confirm row the
 * control height (40px), whatever its `size`, so a template that sets `size` there says
 * something that the page does not show. This spec forbids it, and it forbids a footer group
 * (a group in an element whose class names a foot) that is not a confirm row.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const SRC = join(__dirname, '..');
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
  tag.name === 'app-copy-button' ||
  ((tag.name === 'a' || tag.name === 'button') && attrNames(tag.attrs).includes('appbutton'));

const isConfirmRow = (tag: Tag): boolean =>
  attrNames(tag.attrs).includes('dialog-footer') ||
  (tag.name === 'app-button-group' && /\[main\]="true"/.test(tag.attrs)) ||
  /class="[^"]*\bbtn-grp--main\b/.test(tag.attrs);

/** A class that names the foot of a dialog, a sheet or a form (`ms__foot`, `bs__confirmFoot`). */
const isFoot = (tag: Tag): boolean => /class="[^"]*(?:__foot\b|Foot\b|__footer\b)/.test(tag.attrs);

const sized = (tag: Tag): boolean => /(?:^|\s)(?:size="(?:sm|lg)"|\[size\]=)/.test(tag.attrs);

/** The line of each finding of `source`: a sized button in a confirm row, a foot group that is no confirm row. */
export function confirmRowFindings(source: string): readonly number[] {
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
      const inRow = isConfirmRow(tag) || acc.stack.some(isConfirmRow);
      const parent = acc.stack.at(-1);
      const footGroup =
        name === 'app-button-group' &&
        !isConfirmRow(tag) &&
        (isFoot(tag) || (parent !== undefined && isFoot(parent)));
      const bad = (isButton(tag) && inRow && sized(tag)) || footGroup;
      const found = bad ? [...acc.found, text.slice(0, m.index).split('\n').length] : acc.found;
      const closed = Boolean(m[4]) || VOID.has(name);
      return { stack: closed ? acc.stack : [...acc.stack, tag], found };
    },
    { stack: [], found: [] },
  ).found;
}

describe('ConfirmRowTemplates', () => {
  it('finds a sized button in a confirm row and a foot group that is no confirm row', () => {
    expect(
      confirmRowFindings(
        '<app-button-group [main]="true">\n<app-button size="sm">A</app-button></app-button-group>',
      ),
    ).toEqual([2]);
    expect(
      confirmRowFindings('<div dialog-footer>\n<app-button size="lg">A</app-button></div>'),
    ).toEqual([2]);
    expect(
      confirmRowFindings(
        '<app-dialog><app-button dialog-footer [size]="s()">A</app-button></app-dialog>',
      ),
    ).toEqual([1]);
    expect(
      confirmRowFindings(
        '<div class="x__foot">\n<app-button-group><app-button>A</app-button></app-button-group></div>',
      ),
    ).toEqual([2]);
    expect(
      confirmRowFindings(
        '<app-button-group class="ms__foot" [main]="true"><app-button>A</app-button></app-button-group>',
      ),
    ).toEqual([]);
    expect(
      confirmRowFindings(
        '<app-button-group><app-button size="sm">A</app-button></app-button-group>',
      ),
    ).toEqual([]);
    expect(
      confirmRowFindings('<!-- <div dialog-footer><app-button size="sm">A</app-button></div> -->'),
    ).toEqual([]);
  });

  it('gives every confirm row buttons of one size (001960)', () => {
    const offenders = htmlFiles(join(SRC, 'app')).flatMap((path) =>
      confirmRowFindings(readFileSync(path, 'utf8')).map(
        (line) => `${relative(SRC, path)}:${line}`,
      ),
    );
    expect(offenders).toEqual([]);
  });
});
