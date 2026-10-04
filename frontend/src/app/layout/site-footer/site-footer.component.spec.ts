import { signal } from '@angular/core';
import { render, screen, within } from '@testing-library/angular';
import { BrandingService } from '@core/branding/branding.service';
import { SiteFooterComponent } from './site-footer.component';

function branding(over: Partial<Record<'copyright' | 'legalLinks' | 'footerColumns', unknown>> = {}) {
  return {
    copyright: signal(over.copyright ?? null),
    legalLinks: signal(over.legalLinks ?? []),
    footerColumns: signal(over.footerColumns ?? []),
  };
}

async function setup(value = branding()) {
  localStorage.setItem('ap.locale', 'de');
  return render(SiteFooterComponent, { providers: [{ provide: BrandingService, useValue: value }] });
}

describe('SiteFooterComponent', () => {
  afterEach(() => localStorage.clear());

  it('falls back to the co-branding line without configuration', async () => {
    const { container } = await setup();
    expect(screen.getByText('Eine Plattform des Studierendenparlaments')).toBeInTheDocument();
    expect(container.querySelector('.ft__cols')).toBeNull();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('shows the copyright and the legal links of the active locale', async () => {
    await setup(
      branding({
        copyright: { de: '© AStA', en: '© Student union' },
        legalLinks: [
          { label: { de: 'Impressum', en: 'Imprint' }, url: 'https://example.org/i' },
          { label: { de: 'Datenschutz' }, url: 'https://example.org/d' },
        ],
      }),
    );
    expect(screen.getByText('© AStA')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Impressum' })).toHaveAttribute('href', 'https://example.org/i');
    expect(screen.getByRole('link', { name: 'Datenschutz' })).toBeInTheDocument();
  });

  it('shows the footer columns with their heading and links, and leaves out empty ones', async () => {
    const { container } = await setup(
      branding({
        footerColumns: [
          { label: { de: 'Kontakt' }, links: [{ label: { de: 'Büro' }, url: 'https://example.org/b' }] },
          { label: {}, links: [] },
        ],
      }),
    );
    expect(container.querySelectorAll('.ft__col')).toHaveLength(1);
    const col = container.querySelector('.ft__col') as HTMLElement;
    expect(within(col).getByRole('heading', { name: 'Kontakt' })).toBeInTheDocument();
    expect(within(col).getByRole('link', { name: 'Büro' })).toHaveAttribute('href', 'https://example.org/b');
  });
});
