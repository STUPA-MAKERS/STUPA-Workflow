import { signal } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import { TicketsNoneComponent } from './tickets-none.component';
import { TicketsComponent } from './tickets.component';

function page(over: { loading?: boolean; error?: boolean; hasRows?: boolean } = {}) {
  return {
    loading: signal(over.loading ?? false),
    error: signal(over.error ?? false),
    hasRows: signal(over.hasRows ?? true),
  };
}

async function setup(list: ReturnType<typeof page> | null) {
  localStorage.setItem('ap.locale', 'de');
  return render(TicketsNoneComponent, {
    providers: list ? [{ provide: TicketsComponent, useValue: list }] : [],
  });
}

describe('TicketsNoneComponent', () => {
  afterEach(() => localStorage.clear());

  it('asks for a pick when the list has tickets', async () => {
    await setup(page());
    expect(screen.getByText('Kein Ticket ausgewählt')).toBeInTheDocument();
  });

  it('says that there are no tickets', async () => {
    await setup(page({ hasRows: false }));
    expect(screen.getByText('Keine Tickets')).toBeInTheDocument();
  });

  it.each([
    ['loading', page({ loading: true })],
    ['error', page({ error: true })],
    ['outside the list page', null],
  ])('shows only the empty sheet while %s', async (_label, list) => {
    const { container } = await setup(list);
    expect(container.querySelector('app-empty-state')).toBeNull();
  });
});
