import { Component, inject, input } from '@angular/core';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { ListDetailBarComponent, ListDetailNav, PageHeaderComponent } from '@stupa-makers/ui-kit';
import { BreadcrumbsComponent } from './breadcrumbs.component';

/** A page header as the pages write it: the breadcrumbs of the app in the `[crumbs]` slot. */
@Component({
  standalone: true,
  imports: [PageHeaderComponent, BreadcrumbsComponent],
  template: `
    <app-page-header title="Anträge" [pane]="pane()">
      <app-breadcrumbs crumbs />
    </app-page-header>
  `,
})
class PageComponent {
  readonly pane = input(false);
}

/** An admin page on a phone: the frame shows the bar, the page has its header. */
@Component({
  standalone: true,
  imports: [ListDetailBarComponent, PageHeaderComponent, BreadcrumbsComponent],
  providers: [ListDetailNav],
  template: `
    <app-list-detail-bar />
    <app-page-header title="Flow-Editor">
      <app-breadcrumbs crumbs />
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

describe('page header with the breadcrumbs of the app', () => {
  it('shows the breadcrumbs above the title', async () => {
    const { container } = await render(PageComponent, { providers: [provideRouter([])] });
    expect(container.querySelector('app-page-header > app-breadcrumbs')).not.toBeNull();
    expect(screen.getByRole('heading', { level: 1, name: 'Anträge' })).toBeInTheDocument();
  });

  it('drops the breadcrumbs in the header of a list column', async () => {
    const { container } = await render(PageComponent, {
      providers: [provideRouter([])],
      inputs: { pane: true },
    });
    expect(container.querySelector('app-breadcrumbs')).toBeNull();
  });

  /** The back arrow of the bar replaces the breadcrumbs. */
  it('drops the breadcrumbs below the bar of a one-view page', async () => {
    const view = await render(OneViewPageComponent, { providers: [provideRouter([])] });
    view.fixture.detectChanges();
    expect(view.container.querySelector('app-breadcrumbs')).toBeNull();
    expect(screen.getByRole('button', { name: 'Mehr' }).closest('.ld__barActions')).not.toBeNull();
  });
});
