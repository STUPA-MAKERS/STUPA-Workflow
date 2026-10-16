import { render } from '@testing-library/angular';
import { TodoBoardSkeletonComponent } from './todo-board-skeleton.component';

describe('TodoBoardSkeletonComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('draws four columns of tiles and the place of "+ To-Do" at the foot of each open column', async () => {
    const { container, fixture } = await render(TodoBoardSkeletonComponent, { inputs: { canWrite: true } });
    const cols = container.querySelectorAll('.bv__col');
    expect(cols).toHaveLength(4);
    expect(container.querySelectorAll('.bv__col .bsk__tile').length).toBeGreaterThan(4);
    // The done column (the last) ends without it, as the board does.
    expect(container.querySelectorAll('.bsk__add')).toHaveLength(3);
    expect(cols[3].querySelector('.bsk__add')).toBeNull();
    expect((fixture.nativeElement as HTMLElement).getAttribute('aria-hidden')).toBe('true');
  });

  it('leaves out the place of "+ To-Do" for a person who may not add cards', async () => {
    const { container } = await render(TodoBoardSkeletonComponent);
    expect(container.querySelector('.bsk__add')).toBeNull();
  });

  it('draws the tab row, one column and the dots on a phone', async () => {
    const { container } = await render(TodoBoardSkeletonComponent, { inputs: { phone: true } });
    expect(container.querySelectorAll('.bsk__tab')).toHaveLength(4);
    expect(container.querySelectorAll('.bv__phoneCards .bsk__tile')).toHaveLength(5);
    expect(container.querySelectorAll('.bv__dot')).toHaveLength(4);
    expect(container.querySelector('.bv__col')).toBeNull();
  });

  it('draws the table head and two groups of rows for the list', async () => {
    const { container } = await render(TodoBoardSkeletonComponent, { inputs: { view: 'list' } });
    expect(container.querySelector('.lv__row--head')?.textContent).toContain('Titel');
    const groups = container.querySelectorAll('.lv__group');
    expect(groups).toHaveLength(2);
    expect(groups[0].querySelectorAll('.lv__row')).toHaveLength(5);
    expect(groups[1].querySelectorAll('.lv__row')).toHaveLength(3);
  });
});
