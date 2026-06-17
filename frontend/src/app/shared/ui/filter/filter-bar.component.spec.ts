import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { FilterBarComponent } from './filter-bar.component';

describe('FilterBarComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('renders the trigger button with the i18n default label and is closed initially', async () => {
    const { container } = await render(`<app-filter-bar />`, { imports: [FilterBarComponent] });
    expect(screen.getByRole('button')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).toBeNull();
    // aria-expanded is bound on the app-button host element.
    expect(container.querySelector('app-button')).toHaveAttribute('aria-expanded', 'false');
  });

  it('uses a custom label when provided', async () => {
    await render(`<app-filter-bar label="Eingrenzen" />`, { imports: [FilterBarComponent] });
    expect(screen.getByRole('button')).toHaveTextContent('Eingrenzen');
  });

  it('shows the active-count badge only when activeCount > 0', async () => {
    const view = await render(`<app-filter-bar [activeCount]="count" />`, {
      imports: [FilterBarComponent],
      componentProperties: { count: 0 },
    });
    expect(view.container.querySelector('.filter__count')).toBeNull();
    view.rerender({ componentProperties: { count: 3 } });
    expect(view.container.querySelector('.filter__count')?.textContent).toBe('3');
  });

  it('toggles the popover open and closed via the trigger', async () => {
    const { container } = await render(`<app-filter-bar />`, { imports: [FilterBarComponent] });
    const trigger = screen.getByRole('button', { name: /Filter/i });
    await userEvent.click(trigger);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(container.querySelector('app-button')).toHaveAttribute('aria-expanded', 'true');
    await userEvent.click(trigger);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('emits openChange when toggled', async () => {
    const openChange = jest.fn();
    await render(`<app-filter-bar (openChange)="onOpenChange($event)" />`, {
      imports: [FilterBarComponent],
      componentProperties: { onOpenChange: openChange },
    });
    const trigger = screen.getByRole('button', { name: /Filter/i });
    await userEvent.click(trigger);
    expect(openChange).toHaveBeenLastCalledWith(true);
    await userEvent.click(trigger);
    expect(openChange).toHaveBeenLastCalledWith(false);
  });

  it('shows Apply + Reset in apply mode and emits apply (which closes the popover)', async () => {
    const apply = jest.fn();
    await render(`<app-filter-bar (apply)="onApply()" />`, {
      imports: [FilterBarComponent],
      componentProperties: { onApply: apply },
    });
    await userEvent.click(screen.getByRole('button')); // open
    const applyBtn = screen.getByRole('button', { name: /Anwenden/i });
    const resetBtn = screen.getByRole('button', { name: /Zurücksetzen/i });
    expect(applyBtn).toBeInTheDocument();
    expect(resetBtn).toBeInTheDocument();
    await userEvent.click(applyBtn);
    expect(apply).toHaveBeenCalledTimes(1);
    // Apply closes the popover.
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('emits reset without closing the popover', async () => {
    const reset = jest.fn();
    await render(`<app-filter-bar (reset)="onReset()" />`, {
      imports: [FilterBarComponent],
      componentProperties: { onReset: reset },
    });
    await userEvent.click(screen.getByRole('button')); // open
    await userEvent.click(screen.getByRole('button', { name: /Zurücksetzen/i }));
    expect(reset).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('dialog')).toBeInTheDocument(); // stays open
  });

  it('in live mode hides Apply and hides Reset when no active filters', async () => {
    await render(`<app-filter-bar [live]="true" [activeCount]="0" />`, {
      imports: [FilterBarComponent],
    });
    await userEvent.click(screen.getByRole('button')); // open
    expect(screen.queryByRole('button', { name: /Anwenden/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /Zurücksetzen/i })).toBeNull();
  });

  it('in live mode shows Reset when there are active filters', async () => {
    await render(`<app-filter-bar [live]="true" [activeCount]="2" />`, {
      imports: [FilterBarComponent],
    });
    await userEvent.click(screen.getByRole('button')); // open
    expect(screen.queryByRole('button', { name: /Anwenden/i })).toBeNull();
    expect(screen.getByRole('button', { name: /Zurücksetzen/i })).toBeInTheDocument();
  });

  it('honours custom apply/reset labels', async () => {
    await render(`<app-filter-bar applyLabel="OK" resetLabel="Clear" />`, {
      imports: [FilterBarComponent],
    });
    await userEvent.click(screen.getByRole('button')); // open
    expect(screen.getByRole('button', { name: 'OK' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear' })).toBeInTheDocument();
  });

  it('closes when clicking outside the host', async () => {
    await render(
      `<div><app-filter-bar /></div><button id="outside">outside</button>`,
      { imports: [FilterBarComponent] },
    );
    await userEvent.click(screen.getByRole('button', { name: /Filter/i }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await userEvent.click(document.getElementById('outside') as HTMLButtonElement);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('does not close on a click inside the host', async () => {
    await render(`<app-filter-bar />`, { imports: [FilterBarComponent] });
    await userEvent.click(screen.getByRole('button'));
    const dialog = screen.getByRole('dialog');
    await userEvent.click(dialog);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('ignores a document click while already closed', async () => {
    const openChange = jest.fn();
    await render(`<app-filter-bar (openChange)="onOpenChange($event)" />`, {
      imports: [FilterBarComponent],
      componentProperties: { onOpenChange: openChange },
    });
    // Popover is closed → document click must be a no-op (no openChange emit).
    await userEvent.click(document.body);
    expect(openChange).not.toHaveBeenCalled();
  });

  it('closes on Escape when open', async () => {
    await render(`<app-filter-bar />`, { imports: [FilterBarComponent] });
    await userEvent.click(screen.getByRole('button'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('exposes isOpen reflecting the open state', async () => {
    const view = await render(`<app-filter-bar />`, { imports: [FilterBarComponent] });
    const cmp = view.fixture.debugElement.children[0]
      .componentInstance as FilterBarComponent;
    expect(cmp.isOpen()).toBe(false);
    cmp.toggle();
    view.fixture.detectChanges();
    expect(cmp.isOpen()).toBe(true);
    cmp.close();
    view.fixture.detectChanges();
    expect(cmp.isOpen()).toBe(false);
  });
});
