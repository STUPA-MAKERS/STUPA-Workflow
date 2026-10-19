import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { MeetingsViewActionsComponent } from './meetings-view-actions.component';

describe('MeetingsViewActionsComponent', () => {
  const abo = () => ({ isOpen: jest.fn(() => false), toggle: jest.fn() });

  it('shows the view switch, then the calendar button that opens the subscription', async () => {
    const popover = abo();
    const viewChange = jest.fn();
    const { container } = await render(
      `<app-meetings-view-actions view="list" [abo]="abo" (viewChange)="viewChange($event)" />`,
      { imports: [MeetingsViewActionsComponent], componentProperties: { abo: popover, viewChange } },
    );
    const host = container.querySelector('app-meetings-view-actions')!;
    expect(host.firstElementChild?.tagName).toBe('APP-MEETINGS-VIEW-SWITCH');
    const button = screen.getByRole('button', { name: 'Kalender-Abo' });
    expect(button).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(button);
    expect(popover.toggle).toHaveBeenCalledWith(button.closest('app-button') ?? button);
  });

  it('leaves the switch out when the page has no second view', async () => {
    const { container } = await render(`<app-meetings-view-actions view="list" [abo]="abo" [showSwitch]="false" />`, {
      imports: [MeetingsViewActionsComponent],
      componentProperties: { abo: abo() },
    });
    expect(container.querySelector('app-meetings-view-switch')).toBeNull();
    expect(screen.getByRole('button', { name: 'Kalender-Abo' })).toBeInTheDocument();
  });
});
