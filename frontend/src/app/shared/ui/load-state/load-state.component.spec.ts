import { render, screen } from '@testing-library/angular';
import { runAxe } from '../../../../testing/a11y';
import { LoadStateComponent } from './load-state.component';

const TEMPLATE = `
  <app-load-state [state]="state" [lines]="2" [forbiddenText]="forbidden" errorText="Laden fehlgeschlagen.">
    <ng-template #content><p>Inhalt</p></ng-template>
  </app-load-state>`;

async function setup(state: string, forbidden: string | null = 'Kein Zugriff.') {
  return render(TEMPLATE, { imports: [LoadStateComponent], componentProperties: { state, forbidden } });
}

describe('LoadStateComponent', () => {
  it('shows skeleton lines while loading, and not the content', async () => {
    const { container } = await setup('loading');
    expect(container.querySelector('app-skeleton')).toBeTruthy();
    expect(screen.queryByText('Inhalt')).toBeNull();
  });

  it('shows the content once the data is there', async () => {
    const { container } = await setup('ok');
    expect(screen.getByText('Inhalt')).toBeInTheDocument();
    expect(container.querySelector('app-skeleton, app-note')).toBeNull();
  });

  it('names a missing right in a warning note', async () => {
    const { container } = await setup('forbidden');
    expect(screen.getByRole('alert')).toHaveTextContent('Kein Zugriff.');
    expect(container.querySelector('app-note')).toHaveClass('note--warn');
    expect(screen.queryByText('Inhalt')).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows nothing for a missing right without a text', async () => {
    const { container } = await setup('forbidden', null);
    expect(container.querySelector('app-note')).toBeNull();
    expect(screen.queryByText('Inhalt')).toBeNull();
  });

  it('names a failed read in an error note', async () => {
    const { container } = await setup('error');
    expect(screen.getByRole('alert')).toHaveTextContent('Laden fehlgeschlagen.');
    expect(container.querySelector('app-note')).toHaveClass('note--error');
  });

  it('shows the loading template of the page in place of the lines', async () => {
    const { container } = await render(
      `<app-load-state state="loading" errorText="x">
         <ng-template #loading><p>Formular lädt</p></ng-template>
         <ng-template #content><p>Inhalt</p></ng-template>
       </app-load-state>`,
      { imports: [LoadStateComponent] },
    );
    expect(screen.getByText('Formular lädt')).toBeInTheDocument();
    expect(container.querySelector('app-skeleton')).toBeNull();
  });

  it('shows nothing in the ok state without a content template', async () => {
    const { container } = await render(`<app-load-state state="ok" errorText="x" />`, {
      imports: [LoadStateComponent],
    });
    expect(container.querySelector('app-load-state')?.textContent?.trim()).toBe('');
  });
});
