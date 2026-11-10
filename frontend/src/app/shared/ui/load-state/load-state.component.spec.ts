import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { render, screen } from '@testing-library/angular';
import { runAxe } from '../../../../testing/a11y';
import { LoadStateComponent, loadStateOf } from './load-state.component';
import { loadErrorToast, retryLoadError } from '../../../../testing/load-error';

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

  /** § 000576: a failed read shows a toast with a retry, and no note in the page. */
  it('names a failed read in an error toast with a retry, not in a note', async () => {
    const retry = jest.fn();
    const { container } = await render(
      `<app-load-state state="error" errorText="Laden fehlgeschlagen." (retry)="retry()" />`,
      { imports: [LoadStateComponent], componentProperties: { retry } },
    );
    expect(loadErrorToast()).toBe('Laden fehlgeschlagen.');
    expect(container.querySelector('app-note')).toBeNull();
    retryLoadError();
    expect(retry).toHaveBeenCalledTimes(1);
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

  /** § 000576: a list keeps its content, or its empty state, under the error toast. */
  it('keeps the content in the error state when the page asks for it', async () => {
    await render(
      `<app-load-state state="error" errorText="Laden fehlgeschlagen." [keepContent]="true">
         <ng-template #content><p>Inhalt</p></ng-template>
       </app-load-state>`,
      { imports: [LoadStateComponent] },
    );
    expect(loadErrorToast()).toBe('Laden fehlgeschlagen.');
    expect(screen.getByText('Inhalt')).toBeInTheDocument();
  });

  it('derives the state of a list from its loading and its error signal', () => {
    const loading = signal(true);
    const failed = signal(false);
    const state = TestBed.runInInjectionContext(() => loadStateOf(loading, failed));
    expect(state()).toBe('loading');
    loading.set(false);
    expect(state()).toBe('ok');
    failed.set(true);
    expect(state()).toBe('error');
  });
});
