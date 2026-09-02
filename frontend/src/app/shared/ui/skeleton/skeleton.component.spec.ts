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
