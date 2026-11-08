import { TestBed } from '@angular/core/testing';
import { fireEvent, screen, within } from '@testing-library/angular';
import { ImageAltService } from './image-alt.service';

function png(name: string): File {
  return new File(['x'], name, { type: 'image/png' });
}

/** The dialog that is open now. */
function dialog(): HTMLElement {
  return screen.getByRole('dialog', { name: 'Bild beschreiben' });
}

describe('ImageAltService', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => document.querySelectorAll('app-image-alt-dialog').forEach((el) => el.remove()));

  it('asks for a description and gives it back, trimmed', async () => {
    const svc = TestBed.inject(ImageAltService);
    const answer = svc.ask(png('Plan.png'));
    // ngModel writes the first value in a later task.
    await new Promise((r) => setTimeout(r));
    expect(within(dialog()).getByText('Plan.png')).toBeInTheDocument();
    const field = within(dialog()).getByRole('textbox', { name: /Alternativtext/ });
    fireEvent.input(field, { target: { value: '  Grundriss des Saals ' } });
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Einfügen' }));
    await expect(answer).resolves.toBe('Grundriss des Saals');
    expect(document.querySelector('app-image-alt-dialog')).toBeNull();
  });

  it('refuses an empty description, and a decorative image gets an empty text', async () => {
    const svc = TestBed.inject(ImageAltService);
    const answer = svc.ask(png('Linie.png'));
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Einfügen' }));
    TestBed.tick();
    expect(within(dialog()).getByText('Beschreibe das Bild oder markiere es als Schmuck.')).toBeInTheDocument();
    fireEvent.click(within(dialog()).getByRole('checkbox', { name: 'Nur Schmuck, ohne Beschreibung' }));
    TestBed.tick();
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Einfügen' }));
    await expect(answer).resolves.toBe('');
  });

  it('gives null on a cancel and skips that file when it asks for several', async () => {
    const svc = TestBed.inject(ImageAltService);
    const all = svc.askAll([png('a.png'), png('b.png')]);
    await Promise.resolve();
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Abbrechen' }));
    await new Promise((r) => setTimeout(r));
    fireEvent.input(within(dialog()).getByRole('textbox', { name: /Alternativtext/ }), { target: { value: 'B' } });
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Einfügen' }));
    const picked = await all;
    expect(picked.map((p) => [p.file.name, p.alt])).toEqual([['b.png', 'B']]);
  });
});
