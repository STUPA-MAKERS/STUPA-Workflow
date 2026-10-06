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
});
