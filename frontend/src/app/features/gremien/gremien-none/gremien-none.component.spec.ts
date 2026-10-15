import { render, screen } from '@testing-library/angular';
import { GremienStore } from '../gremien.store';
import { gremium } from '../../../../testing/gremien-fixtures';
import { signal } from '@angular/core';
import type { GremiumOverview } from '@core/api/gremien.service';
import { GremienNoneComponent } from './gremien-none.component';

function storeWith(state: { loading?: boolean; error?: boolean; items?: GremiumOverview[] }) {
  return {
    loading: signal(state.loading ?? false),
    error: signal(state.error ?? false),
    items: signal(state.items ?? []),
  };
}

describe('GremienNoneComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('asks to choose a gremium when the list has one', async () => {
    await render(GremienNoneComponent, {
      providers: [{ provide: GremienStore, useValue: storeWith({ items: [gremium()] }) }],
    });
    expect(screen.getByText('Gremium wählen')).toBeTruthy();
  });

  it('says that there is no gremium', async () => {
    await render(GremienNoneComponent, { providers: [{ provide: GremienStore, useValue: storeWith({}) }] });
    expect(screen.getByText('Keine Gremien')).toBeTruthy();
  });

  it.each([
    ['while the list loads', { loading: true }],
    ['after an error', { error: true }],
  ])('shows the empty sheet only %s', async (_label, state) => {
    const view = await render(GremienNoneComponent, {
      providers: [{ provide: GremienStore, useValue: storeWith(state) }],
    });
    expect(view.container.textContent?.trim()).toBe('');
  });

  it('shows the empty sheet only without a store', async () => {
    const view = await render(GremienNoneComponent);
    expect(view.container.textContent?.trim()).toBe('');
  });
});
