import { signal } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { I18nMap } from '@core/api/models';
import { BrandingService } from '@core/branding/branding.service';
import { runAxe } from '../../../testing/a11y';
import { HelpService } from '../help/help.service';
import { AccessibilityStatementComponent } from './accessibility-statement.component';

async function setup(statement: I18nMap | undefined, loaded = true) {
  localStorage.setItem('ap.locale', 'de');
  const view = await render(AccessibilityStatementComponent, {
    providers: [
      {
        provide: BrandingService,
        useValue: { loaded: signal(loaded), freetexts: signal({ accessibilityStatement: statement }) },
      },
    ],
  });
  const help = view.fixture.debugElement.injector.get(HelpService);
  return { ...view, help };
}

describe('AccessibilityStatementComponent', () => {
  afterEach(() => localStorage.clear());

  /** Spec 000495: the admin text, its `##` headings as h2 below the page h1. */
  it('shows the statement of the page language with its headings', async () => {
    const { container } = await setup({
      de: '## Stand der Vereinbarkeit\n\nDiese Plattform ist **teilweise vereinbar**.',
      en: '## Compliance status',
    });
    expect(screen.getByRole('heading', { level: 1, name: 'Erklärung zur Barrierefreiheit' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Stand der Vereinbarkeit' })).toBeInTheDocument();
    expect(screen.getByText('teilweise vereinbar').tagName).toBe('STRONG');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  /** Spec 000497: the button opens the report dialog with the kind "Barriere". */
  it('opens the report dialog with the kind barrier', async () => {
    const { help } = await setup({ de: 'Text' });
    await userEvent.click(screen.getByRole('button', { name: 'Barriere melden' }));
    expect(help.reportOpen()).toBe(true);
    expect(help.presetKind()).toBe('barrier');
  });

  it('says so when the statement is empty', async () => {
    await setup({ de: '  ' });
    expect(screen.getByText('Die Erklärung ist noch nicht ausgefüllt.')).toBeInTheDocument();
  });

  it('shows a skeleton until the config loaded', async () => {
    await setup(undefined, false);
    expect(screen.getByText('Erklärung wird geladen')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Barriere melden' })).toBeInTheDocument();
  });

  /** Spec 000758: the report is a ticket, so it does not show while Tickets is off. */
  it('shows no report section while Tickets is off', async () => {
    localStorage.setItem('ap.features.off', JSON.stringify(['tickets']));
    await setup({ de: 'Text' });
    expect(screen.queryByRole('button', { name: 'Barriere melden' })).toBeNull();
  });
});
