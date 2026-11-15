import { render, screen } from '@testing-library/angular';
import { GremienApiService, type GremiumInfo } from '@core/api/gremien.service';
import { runAxe } from '../../../../testing/a11y';
import { gremienApiMock, gremiumInfo } from '../../../../testing/gremien-fixtures';
import { loadErrorToast, retryLoadError } from '../../../../testing/load-error';
import { GremiumInfoComponent } from './gremium-info.component';

const FILLED = gremiumInfo({
  bodyMd: '# Willkommen\n\n<script>alert(1)</script>',
  links: [
    { label: 'Wiki', url: 'https://wiki.example.org/stupa' },
    { label: 'Vorsitz', url: 'mailto:vorsitz@example.org' },
  ],
  version: 3,
  updatedAt: '2026-11-15T10:00:00Z',
  updatedByName: 'Mara Keller',
});

async function setup(info: GremiumInfo | null | undefined) {
  localStorage.setItem('ap.locale', 'de');
  const api = gremienApiMock();
  const view = await render(GremiumInfoComponent, {
    inputs: { gremiumId: 'g-1', gremiumName: 'Studierendenparlament', info },
    providers: [{ provide: GremienApiService, useValue: api }],
  });
  return { ...view, api, cmp: view.fixture.componentInstance };
}

describe('GremiumInfoComponent', () => {
  afterEach(() => localStorage.clear());

  it('shows the text, the links in their order and the last change (§ 000950)', async () => {
    const { container } = await setup(FILLED);
    expect(screen.getByRole('heading', { name: 'Willkommen' })).toBeTruthy();
    const links = screen.getAllByRole('link');
    expect(links.map((a) => a.getAttribute('href'))).toEqual([
      'https://wiki.example.org/stupa',
      'mailto:vorsitz@example.org',
    ]);
    expect(links.every((a) => a.getAttribute('target') === '_blank')).toBe(true);
    expect(links.every((a) => a.getAttribute('rel') === 'noopener')).toBe(true);
    expect(screen.getByText('vorsitz@example.org')).toBeTruthy();
    expect(screen.getByText(/Zuletzt geändert von Mara Keller am/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Info bearbeiten/ })).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('renders a script in the text as text (§ 000953)', async () => {
    const { container } = await setup(FILLED);
    expect(container.querySelector('script')).toBeNull();
    expect(container.textContent).toContain('<script>alert(1)</script>');
  });

  it('names no editor after an erasure', async () => {
    await setup({ ...FILLED, updatedByName: null });
    expect(screen.getByText(/^Zuletzt geändert am/)).toBeTruthy();
  });

  it('gives an editor the edit action, and the empty state when empty (§ 000955)', async () => {
    const { cmp, rerender } = await setup(gremiumInfo({ canEdit: true }));
    expect(screen.getByText('Noch keine Info')).toBeTruthy();
    screen.getByRole('button', { name: /Info bearbeiten/ }).click();
    expect(cmp.editOpen()).toBe(true);
    await rerender({ partialUpdate: true, inputs: { info: { ...FILLED, canEdit: true } } });
    expect(screen.getByRole('button', { name: /Info bearbeiten/ })).toBeTruthy();
    expect(cmp.empty()).toBe(false);
  });

  it('shows a skeleton while loading and the load error with a retry', async () => {
    const { cmp, rerender, container } = await setup(undefined);
    expect(container.querySelector('app-skeleton')).toBeTruthy();
    const reload = jest.fn();
    cmp.reload.subscribe(reload);
    await rerender({ partialUpdate: true, inputs: { info: null } });
    expect(loadErrorToast()).toContain('Die Info konnte nicht geladen werden.');
    retryLoadError();
    expect(reload).toHaveBeenCalled();
  });
});
