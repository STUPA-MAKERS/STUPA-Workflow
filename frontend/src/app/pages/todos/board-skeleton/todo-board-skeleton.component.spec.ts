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

  it('draws the column count it is given and the natural height of a board with rows below', async () => {
    const three = await render(TodoBoardSkeletonComponent, { inputs: { columnCount: 3, natural: true } });
    expect(three.container.querySelectorAll('.bv__col')).toHaveLength(3);
    expect(three.fixture.nativeElement as HTMLElement).toHaveClass('bv-host--natural');
    three.fixture.componentRef.setInput('columnCount', 6);
    three.fixture.componentRef.setInput('phone', true);
    three.fixture.componentRef.setInput('natural', false);
    three.fixture.detectChanges();
    const six = three;
    expect(six.container.querySelectorAll('.bsk__tab')).toHaveLength(6);
    expect(six.container.querySelectorAll('.bv__dot')).toHaveLength(6);
    expect(six.fixture.nativeElement as HTMLElement).not.toHaveClass('bv-host--natural');
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

  it('draws board sections of full-width tiles for the phone list', async () => {
    const { container } = await render(TodoBoardSkeletonComponent, { inputs: { view: 'rows', phone: true } });
    const sections = container.querySelectorAll('.bsk__section');
    expect(sections).toHaveLength(3);
    expect(sections[1].querySelectorAll('.bsk__list .bsk__tile')).toHaveLength(3);
    expect(container.querySelector('.bsk__tab')).toBeNull();
    expect(container.querySelector('.bv__dot')).toBeNull();
  });
});
