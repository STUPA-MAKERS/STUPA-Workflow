import { render, screen } from '@testing-library/angular';
import { runAxe } from '../../../../testing/a11y';
import { NoteComponent } from './note.component';

describe('NoteComponent', () => {
  it('shows its text next to a decorative icon', async () => {
    const { container } = await render(
      `<app-note>Ein Angebot ist Pflicht.</app-note>`,
      { imports: [NoteComponent] },
    );
    expect(screen.getByText('Ein Angebot ist Pflicht.')).toBeInTheDocument();
    expect(container.querySelector('app-icon')).toBeTruthy();
    expect(container.querySelector('app-note')).toHaveClass('note--neutral');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('takes the tone and the icon it is given', async () => {
    const { container } = await render(
      `<app-note kind="error" icon="alert">Speicher voll</app-note>`,
      { imports: [NoteComponent] },
    );
    expect(container.querySelector('app-note')).toHaveClass('note--error');
  });

  it('adds no live region by itself', async () => {
    const { container } = await render(`<app-note kind="warn">Hinweis</app-note>`, {
      imports: [NoteComponent],
    });
    expect(container.querySelector('[role="status"], [role="alert"]')).toBeNull();
  });

  it('shows no button without retryable', async () => {
    await render(`<app-note kind="error">Fehler</app-note>`, { imports: [NoteComponent] });
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('offers "Erneut versuchen" when retryable and emits retry on a press', async () => {
    const retry = jest.fn();
    const { container } = await render(
      `<app-note kind="error" icon="alert" role="alert" retryable (retry)="retry()">Laden fehlgeschlagen</app-note>`,
      { imports: [NoteComponent], componentProperties: { retry } },
    );
    screen.getByRole('button', { name: 'Erneut versuchen' }).click();
    expect(retry).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('alert')).toHaveTextContent('Laden fehlgeschlagen');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('takes the surface of a sheet and the ok tone', async () => {
    const { container } = await render(
      `<app-note kind="ok" icon="check" [surface]="3">Importiert</app-note><app-note>Seite</app-note>`,
      { imports: [NoteComponent] },
    );
    const [sheet, page] = Array.from(container.querySelectorAll('app-note'));
    expect(sheet).toHaveClass('note--ok');
    expect(sheet).toHaveClass('note--s3');
    expect(page).not.toHaveClass('note--s3');
  });

  it('shows a projected action after the text', async () => {
    const open = jest.fn();
    const { container } = await render(
      `<app-note kind="warn"><span>Gibt es schon</span><button noteAction type="button" (click)="open()">Öffnen</button></app-note>`,
      { imports: [NoteComponent], componentProperties: { open } },
    );
    const button = screen.getByRole('button', { name: 'Öffnen' });
    expect(container.querySelector('.note__text')).not.toContainElement(button);
    button.click();
    expect(open).toHaveBeenCalledTimes(1);
  });
});
