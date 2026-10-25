import { Component, inject } from '@angular/core';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { ListDetailBarComponent, ListDetailNav } from '@stupa-makers/ui-kit';
import { PageHeaderComponent } from './page-header.component';

/** An admin page on a phone: the frame shows the bar, the page has its header. */
@Component({
  standalone: true,
  imports: [ListDetailBarComponent, PageHeaderComponent],
  providers: [ListDetailNav],
  template: `
    <app-list-detail-bar />
    <app-page-header title="Flow-Editor" meta="Version 24 aktiv">
      <span heading class="st">Gültig</span>
      <button actions type="button">Mehr</button>
    </app-page-header>
  `,
})
class OneViewPageComponent {
  readonly nav = inject(ListDetailNav);
  constructor() {
    this.nav.active.set(true);
  }
}

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

  /**
   * This is for a parent that already spaces its children with a gap. Without it the margin and the
   * gap both apply, and the band under the title grows to the sum.
   */
  it('drops its bottom margin when flush', async () => {
    const host = await setup({ flush: true });
    expect(host.classList.contains('ph--flush')).toBe(true);
  });

  /**
   * A rail page centres its main column between two margins, and it is also a `wide` route, which
   * removes the cap from `.main`. Without `rail` the header fills the viewport and starts at the
   * gutter while its table starts at the centred column.
   */
  it('takes the content cap back when the page is a rail layout', async () => {
    const host = await setup({ rail: true });
    expect(host.classList.contains('ph--rail')).toBe(true);
  });

  /**
   * A rail page whose host is a flex column with a gap needs both: the cap, so the header sits on
   * the content column, and the flush, so its own margin does not stack on top of the gap of the
   * parent.
   */
  it('can be both flush and railed, which four pages need at once', async () => {
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

  /** Beside an admin page the Verwaltung navigation is no heading, because the page has the h1. */
  it('renders the title as a paragraph when it is no heading of the page', async () => {
    const host = await setup({ pane: true, titleTag: 'p' });
    expect(host.querySelector('h1')).toBeNull();
    expect(host.querySelector('p.ph__title')?.textContent).toBe('Anträge');
  });

  /** The bar shows the title; the header keeps it for screen readers only. */
  it('below the bar of a one-view page hands its actions and its title to the bar and drops the breadcrumbs', async () => {
    const view = await render(OneViewPageComponent, { providers: [provideRouter([])] });
    view.fixture.detectChanges();
    const action = screen.getByRole('button', { name: 'Mehr' });
    expect(action.closest('.ld__barActions')).not.toBeNull();
    expect(view.container.querySelector('.ph__actions')).toBeNull();
    expect(view.container.querySelector('app-breadcrumbs')).toBeNull();
    expect(screen.getByRole('heading', { level: 1, name: 'Flow-Editor' })).toHaveClass('sr-only');
    expect(view.fixture.componentInstance.nav.title()).toBe('Flow-Editor');
  });

  it('below the bar of a one-view page puts the meta and the heading slot on the second line of the bar', async () => {
    const view = await render(OneViewPageComponent, { providers: [provideRouter([])] });
    view.fixture.detectChanges();
    const sub = view.container.querySelector('.ld__barText .ld__barSub');
    expect(sub?.querySelector('.ph__meta')?.textContent).toBe('Version 24 aktiv');
    expect(sub?.querySelector('.st')?.textContent).toBe('Gültig');
    expect(view.container.querySelector('.ph__heading .ph__meta')).toBeNull();
    expect(view.container.querySelector('.ph__heading .st')).toBeNull();
  });
});
