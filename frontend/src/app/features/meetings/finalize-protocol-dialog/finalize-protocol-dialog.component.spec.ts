import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { FinalizeProtocolDialogComponent } from './finalize-protocol-dialog.component';

async function setup() {
  const closed = jest.fn();
  const confirmed = jest.fn();
  const view = await render(FinalizeProtocolDialogComponent, {
    inputs: { open: true, meetingTitle: '34. Sitzung', finalizing: false },
    on: { closed, confirmed },
  });
  return { ...view, closed, confirmed };
}

describe('FinalizeProtocolDialogComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('names the meeting, the public page and the rule on names', async () => {
    await setup();
    const dialog = screen.getByRole('dialog', { name: 'Protokoll finalisieren?' });
    expect(dialog).toHaveTextContent('34. Sitzung');
    expect(dialog).toHaveTextContent('Dieses Protokoll wird öffentlich. Keine Namen Dritter im Freitext.');
    expect(screen.getByRole('switch', { name: /Nicht veröffentlichen/ })).toHaveAttribute(
      'aria-checked',
      'false',
    );
  });

  it('finalizes for the public page by default', async () => {
    const { confirmed } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Finalisieren & versenden' }));
    expect(confirmed).toHaveBeenCalledWith({ publicWithheld: false });
  });

  it('holds the protocol back, and starts again with "publish" on the next opening', async () => {
    const { confirmed, fixture } = await setup();
    await userEvent.click(screen.getByRole('switch', { name: /Nicht veröffentlichen/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Finalisieren & versenden' }));
    expect(confirmed).toHaveBeenCalledWith({ publicWithheld: true });
    fixture.componentRef.setInput('open', false);
    fixture.detectChanges();
    fixture.componentRef.setInput('open', true);
    fixture.detectChanges();
    expect(screen.getByRole('switch', { name: /Nicht veröffentlichen/ })).toHaveAttribute(
      'aria-checked',
      'false',
    );
  });

  it('cancels', async () => {
    const { closed } = await setup();
    await userEvent.click(screen.getAllByRole('button', { name: 'Abbrechen' })[0]);
    expect(closed).toHaveBeenCalled();
  });
});
