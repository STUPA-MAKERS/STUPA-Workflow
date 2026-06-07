import { Component } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ButtonComponent } from './button.component';

describe('ButtonComponent', () => {
  it('renders projected label inside a native button', async () => {
    await render(`<app-button>Speichern</app-button>`, { imports: [ButtonComponent] });
    const btn = screen.getByRole('button', { name: 'Speichern' });
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveClass('btn--primary', 'btn--md');
  });

  it('applies variant and size modifiers', async () => {
    await render(`<app-button variant="danger" size="lg">Löschen</app-button>`, {
      imports: [ButtonComponent],
    });
    expect(screen.getByRole('button')).toHaveClass('btn--danger', 'btn--lg');
  });

  it('adds the icon modifier when iconOnly is set', async () => {
    await render(`<app-button [iconOnly]="true" variant="secondary" size="sm">✕</app-button>`, {
      imports: [ButtonComponent],
    });
    expect(screen.getByRole('button')).toHaveClass('btn--icon', 'btn--secondary', 'btn--sm');
  });

  it('exposes an accessible name via ariaLabel for icon buttons', async () => {
    await render(`<app-button [iconOnly]="true" ariaLabel="Entfernen">✕</app-button>`, {
      imports: [ButtonComponent],
    });
    expect(screen.getByRole('button', { name: 'Entfernen' })).toBeInTheDocument();
  });

  it('disables and marks aria-busy while loading', async () => {
    await render(`<app-button [loading]="true">X</app-button>`, { imports: [ButtonComponent] });
    const btn = screen.getByRole('button');
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute('aria-busy', 'true');
  });

  it('does not emit click when disabled', async () => {
    @Component({
      standalone: true,
      imports: [ButtonComponent],
      template: `<app-button [disabled]="true"><span (click)="onClick()">Go</span></app-button>`,
    })
    class Host {
      clicks = 0;
      onClick(): void {
        this.clicks++;
      }
    }
    const { fixture } = await render(Host);
    await userEvent.click(screen.getByRole('button'));
    expect(fixture.componentInstance.clicks).toBe(0);
  });
});
