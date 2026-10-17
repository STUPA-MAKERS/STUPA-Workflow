import { render, screen } from '@testing-library/angular';
import { SkeletonComponent } from './skeleton.component';

describe('SkeletonComponent', () => {
  it('draws the number of lines it is asked for', async () => {
    const { container } = await render(`<app-skeleton [count]="4" />`, {
      imports: [SkeletonComponent],
    });
    expect(container.querySelectorAll('.skel--line')).toHaveLength(4);
  });

  it('draws one panel regardless of the count', async () => {
    const { container } = await render(`<app-skeleton variant="panel" [count]="4" />`, {
      imports: [SkeletonComponent],
    });
    expect(container.querySelectorAll('.skel--panel')).toHaveLength(1);
  });

  it('draws a leading and a trailing block per row, so a list reads as rows', async () => {
    const { container } = await render(`<app-skeleton variant="rows" [count]="3" />`, {
      imports: [SkeletonComponent],
    });
    expect(container.querySelectorAll('.sk__row')).toHaveLength(3);
    expect(container.querySelectorAll('.skel--bar')).toHaveLength(6);
    // Only the last row rounds the bottom corners of the group.
    expect(container.querySelectorAll('.sk__row--last')).toHaveLength(1);
    expect(container.querySelectorAll('.sk__row')[2]).toHaveClass('sk__row--last');
  });

  it('draws list-item rows: a title line, a sub line of two bars, a trailing value', async () => {
    const { container } = await render(`<app-skeleton variant="items" [count]="8" />`, {
      imports: [SkeletonComponent],
    });
    const rows = container.querySelectorAll('.sk__item');
    expect(rows).toHaveLength(8);
    expect(rows[0].querySelectorAll('.sk__itemTitle .skel-text')).toHaveLength(1);
    expect(rows[0].querySelectorAll('.sk__itemSub .skel-text')).toHaveLength(2);
    expect(rows[0].querySelectorAll('.sk__itemTrail .skel-text')).toHaveLength(1);
    // The widths repeat after six rows, the same on every load.
    const width = (i: number) => (rows[i].querySelector('.sk__itemTitle .skel-text') as HTMLElement).style.width;
    expect(width(6)).toBe(width(0));
    expect(width(1)).not.toBe(width(0));
    expect(container.querySelector('.sk__items')).not.toHaveClass('rowgroup');
    expect(container.querySelector('.sk__items')?.closest('[aria-hidden="true"]')).toBeTruthy();
  });

  it('starts a list-item row with a lead tile and ends it with a person when asked', async () => {
    const { container } = await render(`<app-skeleton variant="items" [count]="3" [lead]="true" trail="avatar" />`, {
      imports: [SkeletonComponent],
    });
    expect(container.querySelectorAll('.sk__item .sk__itemLead')).toHaveLength(3);
    expect(container.querySelectorAll('.sk__item .sk__itemAvatar')).toHaveLength(3);
    expect(container.querySelector('.sk__itemTrail')).toBeNull();
  });

  it('puts list-item rows into a row group when asked, as a one-column list does', async () => {
    const { container } = await render(`<app-skeleton variant="items" [grouped]="true" />`, {
      imports: [SkeletonComponent],
    });
    expect(container.querySelector('.sk__items')).toHaveClass('rowgroup');
  });

  it('draws chat bubbles at both sides, an avatar beside the bubbles of others', async () => {
    const { container } = await render(`<app-skeleton variant="bubbles" [count]="5" />`, {
      imports: [SkeletonComponent],
    });
    const msgs = container.querySelectorAll('.sk__msg');
    expect(msgs).toHaveLength(5);
    const own = container.querySelectorAll('.sk__msg--own');
    expect(own.length).toBeGreaterThan(0);
    expect(own.length).toBeLessThan(5);
    for (const m of msgs) {
      expect(m.querySelectorAll('.sk__avatar')).toHaveLength(m.classList.contains('sk__msg--own') ? 0 : 1);
    }
    expect(container.querySelector('.sk__bubbles')?.closest('[aria-hidden="true"]')).toBeTruthy();
    expect(container.querySelector('.sk__log')).toBeNull();
  });

  it('draws a whole chat: the framed log with bubbles, and the composer when asked', async () => {
    const { container, rerender } = await render(`<app-skeleton variant="chat" [framed]="framed" [composer]="composer" />`, {
      imports: [SkeletonComponent],
      componentProperties: { framed: true, composer: true },
    });
    expect(container.querySelector('.sk__log')).toHaveClass('sk__log--framed');
    expect(container.querySelectorAll('.sk__log .sk__msg').length).toBeGreaterThan(0);
    expect(container.querySelector('.sk__composer')).toBeTruthy();
    expect(container.querySelector('app-skeleton')).toHaveClass('sk-host--chat');
    await rerender({ componentProperties: { framed: false, composer: false } });
    expect(container.querySelector('.sk__log')).not.toHaveClass('sk__log--framed');
    expect(container.querySelector('.sk__composer')).toBeNull();
  });

  it('never draws nothing, whatever count it is given', async () => {
    // A zero or negative count would otherwise render an empty box that still takes
    // its margin — a blank gap where a placeholder belongs.
    const { container } = await render(`<app-skeleton [count]="0" />`, {
      imports: [SkeletonComponent],
    });
    expect(container.querySelectorAll('.skel--line').length).toBeGreaterThan(0);
  });

  it('tells a screen reader what is happening, since the blocks are decorative', async () => {
    await render(`<app-skeleton label="Wird geladen" />`, { imports: [SkeletonComponent] });
    expect(screen.getByRole('status')).toHaveTextContent('Wird geladen');
  });

  it('hides every block from the accessibility tree', async () => {
    const { container } = await render(`<app-skeleton variant="rows" [count]="2" />`, {
      imports: [SkeletonComponent],
    });
    for (const el of container.querySelectorAll('.skel, .sk__row')) {
      expect(el.closest('[aria-hidden="true"]')).toBeTruthy();
    }
  });

  it('omits the status line when it has nothing to say', async () => {
    // An empty `role="status"` is announced as a blank region.
    const { container } = await render(`<app-skeleton />`, { imports: [SkeletonComponent] });
    expect(container.querySelector('[role="status"]')).toBeNull();
  });
});
