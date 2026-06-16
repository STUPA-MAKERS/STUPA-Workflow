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

  it('sets the submit/reset type and adds the block host class', async () => {
    const { container } = await render(`<app-button type="submit" [block]="true">S</app-button>`, {
      imports: [ButtonComponent],
    });
    expect(screen.getByRole('button')).toHaveAttribute('type', 'submit');
    expect(container.querySelector('app-button')).toHaveClass('btn-block');
  });

  it('uses the explicit title as the tooltip', async () => {
    await render(`<app-button title="Tipp">X</app-button>`, { imports: [ButtonComponent] });
    expect(screen.getByRole('button')).toHaveAttribute('title', 'Tipp');
  });

  it('falls back the tooltip to ariaLabel for icon-only buttons', async () => {
    await render(`<app-button [iconOnly]="true" ariaLabel="Löschen">✕</app-button>`, {
      imports: [ButtonComponent],
    });
    expect(screen.getByRole('button')).toHaveAttribute('title', 'Löschen');
  });

  it('has no tooltip for a non-icon button without an explicit title', async () => {
    await render(`<app-button ariaLabel="A11y only">X</app-button>`, {
      imports: [ButtonComponent],
    });
    // ariaLabel must NOT leak into the tooltip for a normal (text) button.
    expect(screen.getByRole('button')).not.toHaveAttribute('title');
  });

  it('applies a custom background color and the btn--custom class', async () => {
    await render(`<app-button color="#222266">C</app-button>`, {
      imports: [ButtonComponent],
    });
    const btn = screen.getByRole('button');
    expect(btn).toHaveClass('btn--custom');
    expect(btn.style.background).toBe('rgb(34, 34, 102)');
    // Dark background → white text.
    expect(btn.style.color).toBe('rgb(255, 255, 255)');
  });

  it('chooses dark text for a light custom color', async () => {
    await render(`<app-button color="#ffee88">C</app-button>`, { imports: [ButtonComponent] });
    expect(screen.getByRole('button').style.color).toBe('rgb(17, 17, 17)');
  });

  it('expands a 3-digit hex color for contrast computation', async () => {
    // #fff → light → dark text.
    await render(`<app-button color="#fff">C</app-button>`, { imports: [ButtonComponent] });
    expect(screen.getByRole('button').style.color).toBe('rgb(17, 17, 17)');
  });

  it('falls back to white text for an invalid hex color', async () => {
    // "not-a-color" cannot be reduced to 6 hex chars → contrastColor returns #ffffff.
    await render(`<app-button color="not-a-color">C</app-button>`, {
      imports: [ButtonComponent],
    });
    expect(screen.getByRole('button').style.color).toBe('rgb(255, 255, 255)');
  });

  it('has no tooltip for an icon-only button without an ariaLabel', async () => {
    // iconOnly true but ariaLabel '' → tooltip() returns null.
    await render(`<app-button [iconOnly]="true">✕</app-button>`, { imports: [ButtonComponent] });
    expect(screen.getByRole('button')).not.toHaveAttribute('title');
  });

  it('handles the low-luminance sRGB channel branch (pure black) → white text', async () => {
    // All channels 0 ⇒ v (0) <= 0.03928 ⇒ linear branch; luminance 0 → white text.
    await render(`<app-button color="#000000">C</app-button>`, { imports: [ButtonComponent] });
    expect(screen.getByRole('button').style.color).toBe('rgb(255, 255, 255)');
  });
});
