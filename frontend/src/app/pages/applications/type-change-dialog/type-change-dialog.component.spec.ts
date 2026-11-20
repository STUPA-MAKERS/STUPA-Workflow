import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ToastService } from '@stupa-makers/ui-kit';
import { USE_MOCK_API } from '@core/api/api.config';
import type { ApplicationType, TypeChangePreview } from '@core/api/models';
import { TypeChangeDialogComponent } from './type-change-dialog.component';

const TYPES: ApplicationType[] = [
  {
    id: 't1',
    name: 'Finanzantrag',
    active: true,
    hasBudget: true,
    activeFormVersionId: 'f1',
    key: 'fin',
    gremiumId: null,
  },
  {
    id: 't2',
    name: 'QSM',
    active: true,
    hasBudget: true,
    activeFormVersionId: 'f2',
    key: 'qsm',
    gremiumId: null,
  },
  {
    id: 't3',
    name: 'Alt',
    active: false,
    hasBudget: false,
    activeFormVersionId: null,
    key: 'alt',
    gremiumId: null,
  },
  {
    id: 't4',
    name: 'Sonstiges',
    active: true,
    hasBudget: false,
    activeFormVersionId: 'f4',
    key: 'so',
    gremiumId: null,
  },
];

@Component({
  changeDetection: ChangeDetectionStrategy.Eager,
  standalone: true,
  imports: [TypeChangeDialogComponent],
  template: `
    <app-type-change-dialog
      [applicationId]="id()"
      [currentTypeId]="current()"
      [types]="types"
      [(open)]="open"
      (done)="done = done + 1"
    />
  `,
})
class Host {
  readonly id = signal<string | null>('app-1');
  readonly current = signal<string | null>('t1');
  readonly open = signal(false);
  readonly types = TYPES;
  done = 0;
}

const BACK = {
  id: 'tr1',
  label: { de: 'Zur Überarbeitung' },
  toStateId: 's1',
  toStateLabel: { de: 'Eingereicht' },
};

const SEND_BACK: TypeChangePreview = {
  typeId: 't2',
  carried: [{ key: 'title', label: { de: 'Titel' } }],
  missing: [
    { key: 'funding', label: { de: 'Förderhöhe' } },
    { key: 'period', label: {} },
  ],
  dropped: [{ key: 'iban', label: { de: 'IBAN' } }],
  transitions: [BACK],
  possible: true,
};

const PLAIN: TypeChangePreview = {
  typeId: 't4',
  carried: [{ key: 'title', label: { de: 'Titel' } }],
  missing: [],
  dropped: [],
  transitions: [],
  possible: true,
};

const PREVIEW_URL =
  (typeId: string) => (r: { url: string; params: { get(k: string): string | null } }) =>
    r.url === '/api/applications/app-1/type-change' && r.params.get('typeId') === typeId;

async function setup() {
  const view = await render(Host, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toast = view.fixture.debugElement.injector.get(ToastService);
  const host = view.fixture.componentInstance;
  const cmp = view.fixture.debugElement.children[0].componentInstance as TypeChangeDialogComponent;
  const openIt = () => {
    host.open.set(true);
    view.detectChanges();
  };
  const pick = (typeId: string, preview: TypeChangePreview) => {
    cmp.pickType(typeId);
    http.expectOne(PREVIEW_URL(typeId)).flush(preview);
    view.detectChanges();
  };
  return { ...view, http, toast, host, cmp, openIt, pick };
}

describe('TypeChangeDialogComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('offers the active types without the current one', async () => {
    const { cmp, openIt } = await setup();
    openIt();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(cmp.typeOptions().map((o) => o.value)).toEqual(['t2', 't4']);
  });

  it('shows the missing, dropped and carried fields and picks the only transition', async () => {
    const { cmp, openIt, pick } = await setup();
    openIt();
    pick('t2', SEND_BACK);
    expect(cmp.missing()).toEqual(['Förderhöhe', 'period']);
    expect(cmp.dropped()).toEqual(['IBAN']);
    expect(cmp.carried()).toEqual(['Titel']);
    expect(cmp.transitionId()).toBe('tr1');
    expect(cmp.transitionOptions().map((o) => o.label)).toEqual([
      'Zur Überarbeitung → Eingereicht',
    ]);
    expect(screen.getByText('Förderhöhe, period')).toBeInTheDocument();
    expect(cmp.canSubmit()).toBe(true);
  });

  it('waits for a pick when several transitions fit', async () => {
    const { cmp, openIt, pick } = await setup();
    openIt();
    pick('t2', { ...SEND_BACK, transitions: [BACK, { ...BACK, id: 'tr2' }] });
    expect(cmp.transitionId()).toBe('');
    expect(cmp.canSubmit()).toBe(false);
    cmp.transitionId.set('tr2');
    expect(cmp.canSubmit()).toBe(true);
  });

  it('says why a change without a way back is not possible', async () => {
    const { cmp, openIt, pick } = await setup();
    openIt();
    pick('t2', { ...SEND_BACK, transitions: [], possible: false });
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(cmp.canSubmit()).toBe(false);
  });

  it('sends back with the transition and the trimmed message', async () => {
    const { http, host, cmp, toast, openIt, pick } = await setup();
    const success = jest.spyOn(toast, 'success');
    openIt();
    pick('t2', SEND_BACK);
    cmp.note.set('  Bitte ergänzen.  ');
    cmp.submit();
    cmp.submit();
    const post = http.expectOne(
      (r) => r.method === 'POST' && r.url === '/api/applications/app-1/type-change',
    );
    expect(post.request.body).toEqual({
      typeId: 't2',
      transitionId: 'tr1',
      note: 'Bitte ergänzen.',
    });
    post.flush({ id: 'app-1', typeId: 't2', data: {} });
    expect(host.open()).toBe(false);
    expect(host.done).toBe(1);
    expect(success).toHaveBeenCalled();
  });

  it('changes without a transition and without a message when nothing is missing', async () => {
    const { http, cmp, openIt, pick } = await setup();
    openIt();
    pick('t4', PLAIN);
    cmp.note.set('egal');
    cmp.submit();
    const post = http.expectOne((r) => r.method === 'POST');
    expect(post.request.body).toEqual({ typeId: 't4', transitionId: null, note: null });
  });

  it('sends a missing field change with an empty message as null', async () => {
    const { http, cmp, openIt, pick } = await setup();
    openIt();
    pick('t2', SEND_BACK);
    cmp.note.set('   ');
    cmp.submit();
    expect(http.expectOne((r) => r.method === 'POST').request.body.note).toBeNull();
  });

  it.each([403, 409, 500])('reports a %s answer and stays open', async (status) => {
    const { http, host, cmp, toast, openIt, pick } = await setup();
    const error = jest.spyOn(toast, 'error');
    openIt();
    pick('t4', PLAIN);
    cmp.submit();
    http.expectOne((r) => r.method === 'POST').flush({}, { status, statusText: 'x' });
    expect(cmp.saving()).toBe(false);
    expect(host.open()).toBe(true);
    expect(host.done).toBe(0);
    expect(error).toHaveBeenCalledTimes(1);
  });

  it.each([
    [500, null, 'applications.typeChange.error.load'],
    [409, 'type_change_not_submitted', 'applications.typeChange.error.notSubmitted'],
    [422, 'type_change_type_not_submittable', 'applications.typeChange.error.noForm'],
    [403, null, 'applications.transitions.forbidden'],
  ])('shows why a %s preview failed and keeps the change off', async (status, code, key) => {
    const { http, cmp, toast, openIt, detectChanges } = await setup();
    const error = jest.spyOn(toast, 'error');
    openIt();
    cmp.pickType('t2');
    expect(cmp.loading()).toBe(true);
    expect(cmp.canSubmit()).toBe(false);
    http.expectOne(PREVIEW_URL('t2')).flush(code ? { code } : {}, { status, statusText: 'x' });
    detectChanges();
    expect(cmp.loading()).toBe(false);
    expect(cmp.preview()).toBeNull();
    expect(cmp.previewError()).toBe(key);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(error).not.toHaveBeenCalled();
    cmp.pickType('t4');
    expect(cmp.previewError()).toBeNull();
    http.expectOne(PREVIEW_URL('t4')).flush(PLAIN);
  });

  it('drops the answer of an earlier pick', async () => {
    const { http, cmp, openIt, detectChanges } = await setup();
    openIt();
    cmp.pickType('t2');
    const first = http.expectOne(PREVIEW_URL('t2'));
    cmp.pickType('t4');
    first.flush(SEND_BACK);
    expect(cmp.preview()).toBeNull();
    http.expectOne(PREVIEW_URL('t4')).flush({}, { status: 500, statusText: 'x' });
    expect(cmp.previewError()).toBe('applications.typeChange.error.load');
    cmp.pickType('t2');
    expect(cmp.previewError()).toBeNull();
    const third = http.expectOne(PREVIEW_URL('t2'));
    cmp.close();
    detectChanges();
    openIt();
    third.flush({}, { status: 500, statusText: 'x' });
    expect(cmp.previewError()).toBeNull();
    expect(cmp.loading()).toBe(false);
  });

  it('has no lists and no transitions before a preview', async () => {
    const { cmp, openIt } = await setup();
    openIt();
    expect(cmp.transitionOptions()).toEqual([]);
    expect(cmp.missing()).toEqual([]);
    expect(cmp.dropped()).toEqual([]);
    expect(cmp.carried()).toEqual([]);
    expect(cmp.canSubmit()).toBe(false);
  });

  it('drops the answer of a successful preview after the dialog closed', async () => {
    const { http, cmp, openIt } = await setup();
    openIt();
    cmp.pickType('t2');
    const req = http.expectOne(PREVIEW_URL('t2'));
    cmp.close();
    req.flush(SEND_BACK);
    expect(cmp.preview()).toBeNull();
    expect(cmp.loading()).toBe(false);
  });

  it('loads nothing without a type or without an application', async () => {
    const { http, host, cmp, detectChanges, openIt } = await setup();
    openIt();
    cmp.pickType('');
    host.id.set(null);
    detectChanges();
    cmp.pickType('t2');
    cmp.submit();
    http.verify();
  });

  /**
   * The test clicks the footer button, because the close button of the dialog has the same name.
   */
  it('closes on "Abbrechen" and starts empty on the next opening', async () => {
    const { host, cmp, detectChanges, openIt, pick } = await setup();
    openIt();
    pick('t2', SEND_BACK);
    cmp.note.set('x');
    const cancel = screen
      .getAllByRole('button', { name: 'Abbrechen' })
      .find((b) => !b.classList.contains('dialog__close'));
    await userEvent.click(cancel!);
    expect(host.open()).toBe(false);
    host.open.set(true);
    detectChanges();
    expect(cmp.typeId()).toBe('');
    expect(cmp.note()).toBe('');
    expect(cmp.preview()).toBeNull();
  });
});
