import { render } from '@testing-library/angular';
import { PageHeaderComponent } from './page-header.component';

/**
 * The header carries two layout flags, and both exist because of a misalignment that
 * shipped. They are worth asserting: neither is visible in a unit test's output, and
 * neither page that needs them has a test of its own that would catch a regression.
 */
describe('PageHeaderComponent', () => {
  async function setup(inputs: Record<string, unknown> = {}) {
    const view = await render(PageHeaderComponent, {
      inputs: { title: 'Anträge', ...inputs },
    });
    return view.fixture.nativeElement as HTMLElement;
  }

  it('renders the title', async () => {
    const host = await setup();
    expect(host.textContent).toContain('Anträge');
  });

  it('carries no layout class by default', async () => {
    const host = await setup();
    expect(host.classList.contains('ph--flush')).toBe(false);
    expect(host.classList.contains('ph--rail')).toBe(false);
  });

  it('drops its bottom margin when flush', async () => {
    // For a parent that already spaces its children with a gap. Without this the margin
    // and the gap both apply and the band under the title grows to the sum.
    const host = await setup({ flush: true });
    expect(host.classList.contains('ph--flush')).toBe(true);
  });

  it('takes the content cap back when the page is a rail layout', async () => {
    // A rail page centres its main column between two margins, and it is also a `wide`
    // route, which removes the cap from `.main`. Without `rail` the header filled the
    // viewport and started at the gutter while its table started at the centred column:
    // at 1920px the title sat at x=24 and the table at x=363.
    const host = await setup({ rail: true });
    expect(host.classList.contains('ph--rail')).toBe(true);
  });

  it('can be both flush and railed, which four pages need at once', async () => {
    // A rail page whose host is a flex column with a gap needs both: the cap so the
    // header sits on the content column, and the flush so its own margin does not stack
    // on top of the parent's gap. Missing the second one put 40px of nothing under the
    // heading on the budget tab.
    const host = await setup({ rail: true, flush: true });
    expect(host.classList.contains('ph--rail')).toBe(true);
    expect(host.classList.contains('ph--flush')).toBe(true);
  });

  it('shows the meta text in the title block, not in the actions slot', async () => {
    const host = await setup({ meta: '8 offen' });
    const meta = host.querySelector('.ph__heading .ph__meta');
    expect(meta?.textContent).toBe('8 offen');
    expect(host.querySelector('.ph__actions .ph__meta')).toBeNull();
  });

  it('renders no meta element without a meta text', async () => {
    const host = await setup();
    expect(host.querySelector('.ph__meta')).toBeNull();
  });

  it('puts a status of the heading slot in the title block, beside the title', async () => {
    const { container } = await render(
      `<app-page-header title="Förderantrag"><span heading class="st">Aktiv</span><button actions>Speichern</button></app-page-header>`,
      { imports: [PageHeaderComponent] },
    );
    const heading = container.querySelector('.ph__heading');
    expect(heading?.querySelector('.st')?.textContent).toBe('Aktiv');
    expect(container.querySelector('.ph__actions')?.textContent).toBe('Speichern');
  });

  it('is the header of a list column with `pane`: no breadcrumbs, an h1 with an id', async () => {
    const host = await setup({ pane: true, titleId: 'apps-title' });
    expect(host.classList.contains('ph--pane')).toBe(true);
    expect(host.querySelector('app-breadcrumbs')).toBeNull();
    const title = host.querySelector('h1.ph__title');
    expect(title?.id).toBe('apps-title');
  });

  it('keeps the breadcrumbs and gives the title no id by default', async () => {
    const host = await setup();
    expect(host.querySelector('app-breadcrumbs')).not.toBeNull();
    expect(host.querySelector('h1.ph__title')?.hasAttribute('id')).toBe(false);
  });

  it('renders the title as a paragraph when it is no heading of the page', async () => {
    // The Verwaltung navigation beside an admin page: the page has the h1.
    const host = await setup({ pane: true, titleTag: 'p' });
    expect(host.querySelector('h1')).toBeNull();
    expect(host.querySelector('p.ph__title')?.textContent).toBe('Anträge');
  });
});
