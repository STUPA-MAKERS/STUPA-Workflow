import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/** One placeholder tile: a label line or not, one or two title lines, a fact bar. */
interface SkelTile {
  label: string | null;
  title: readonly string[];
  fact: string;
}

/** Placeholder columns. Four, as a new board has; the widths are fixed per place. */
const COLUMNS: readonly { name: string; tiles: readonly SkelTile[] }[] = [
  {
    name: '3.5rem',
    tiles: [
      { label: '5.5rem', title: ['88%', '42%'], fact: '5.5rem' },
      { label: '3.5rem', title: ['80%', '30%'], fact: '3rem' },
      { label: null, title: ['86%'], fact: '4rem' },
    ],
  },
  {
    name: '4.5rem',
    tiles: [
      { label: '7rem', title: ['84%'], fact: '7.5rem' },
      { label: '3.5rem', title: ['78%'], fact: '6rem' },
    ],
  },
  {
    name: '3.75rem',
    tiles: [
      { label: '5.5rem', title: ['80%', '50%'], fact: '4.5rem' },
      { label: '3.5rem', title: ['86%', '36%'], fact: '0' },
    ],
  },
  {
    name: '4rem',
    tiles: [
      { label: '3.5rem', title: ['82%'], fact: '3rem' },
      { label: '4rem', title: ['76%'], fact: '3rem' },
      { label: null, title: ['70%', '40%'], fact: '3rem' },
    ],
  },
];

/** The phone shows one column: five tiles. */
const PHONE_TILES: readonly SkelTile[] = [
  { label: '5.5rem', title: ['84%'], fact: '6.5rem' },
  { label: '3.5rem', title: ['78%'], fact: '3rem' },
  { label: null, title: ['88%'], fact: '4.5rem' },
  { label: '4rem', title: ['70%'], fact: '3rem' },
  { label: '3.5rem', title: ['74%'], fact: '2.5rem' },
];

/** The list shows two groups of rows; the widths are fixed per place. */
const LIST_GROUPS: readonly { name: string; rows: readonly { title: string; link: string; label: string; due: string }[] }[] = [
  {
    name: '3.5rem',
    rows: [
      { title: '62%', link: '0', label: '70%', due: '60%' },
      { title: '70%', link: '80%', label: '45%', due: '35%' },
      { title: '66%', link: '75%', label: '0', due: '35%' },
      { title: '58%', link: '0', label: '50%', due: '35%' },
      { title: '54%', link: '0', label: '45%', due: '0' },
    ],
  },
  {
    name: '4.5rem',
    rows: [
      { title: '60%', link: '80%', label: '75%', due: '35%' },
      { title: '56%', link: '65%', label: '40%', due: '55%' },
      { title: '64%', link: '0', label: '65%', due: '0' },
    ],
  },
];

/**
 * The board while it loads, in the geometry of `app-todo-board-view` and
 * `app-todo-list-view`: it shares their stylesheets, so the column frames, heads,
 * scroll areas and the column foot, or the table head and the rows, are the real ones.
 * The placeholder tiles have the box of `app-todo-card-tile`. The phone shows the tab
 * row, one column of tiles and the dots.
 *
 * The frames show at once; the bars inside show after 300ms (`skel-in`), so a fast
 * answer shows no bars at all. The blocks are hidden from the accessibility tree; the
 * page carries the `role="status"` line.
 */
@Component({
  selector: 'app-todo-board-skeleton',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet, TranslatePipe],
  templateUrl: './todo-board-skeleton.component.html',
  styleUrls: [
    '../board-view/todo-board-view.component.scss',
    '../list-view/todo-list-view.component.scss',
    './todo-board-skeleton.component.scss',
  ],
  host: { 'aria-hidden': 'true' },
})
export class TodoBoardSkeletonComponent {
  readonly view = input<'board' | 'list'>('board');
  readonly phone = input(false);
  /** The person may add cards: each open column ends with the place of "+ To-Do". */
  readonly canWrite = input(false);

  protected readonly columns = COLUMNS;
  protected readonly phoneTiles = PHONE_TILES;
  protected readonly groups = LIST_GROUPS;
}
