import { Component, signal } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ToastService } from '@stupa-makers/ui-kit';
import { USE_MOCK_API } from '@core/api/api.config';
import type { StateOutWire } from '@core/api/models';
import { ForceStatusDialogComponent } from './force-status-dialog.component';

@Component({
  standalone: true,
  imports: [ForceStatusDialogComponent],
  template: `
    <app-force-status-dialog
      [applicationId]="id()"
      [currentStateId]="current()"
      [(open)]="open"
      (done)="done = done + 1"
    />
  `,
})
class Host {
  readonly id = signal<string | null>('app-1');
  readonly current = signal<string | null>('s1');
  readonly open = signal(false);
  done = 0;
}

const STATES: StateOutWire[] = [
  { id: 's1', key: 'submitted', label: { de: 'Eingereicht' }, color: null, editAllowed: true },
  { id: 's2', key: 'review', label: { de: 'In Prüfung' }, color: null, editAllowed: false },
  { id: 's3', key: 'closed', label: {}, color: null, editAllowed: false },
];

const STATES_URL = (r: { url: string }) => r.url === '/api/applications/app-1/flow-states';

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
  const cmp = view.fixture.debugElement.children[0].componentInstance as ForceStatusDialogComponent;
  const openIt = () => {
    host.open.set(true);
    view.detectChanges();
    http.expectOne(STATES_URL).flush(STATES);
    view.detectChanges();
  };
  return { ...view, http, toast, host, cmp, openIt };
}

describe('ForceStatusDialogComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads the flow states when it opens and leaves the current one out', async () => {
    const { http, cmp, openIt } = await setup();
    http.verify();
    openIt();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    // A state without a label falls back to its key.
    expect(cmp.options().map((o) => o.value)).toEqual(['s2', 's3']);
    expect(cmp.options().map((o) => o.label)).toEqual(['In Prüfung', 'closed']);
  });

  it('needs a state and a reason before it sends', async () => {
    const { http, cmp, openIt } = await setup();
    openIt();
    cmp.submit();
    cmp.choice.set('s2');
    cmp.note.set('   ');
    cmp.submit();
    http.verify();
  });

  it('forces the state with the reason, closes and reports done', async () => {
    const { http, host, cmp, toast, openIt } = await setup();
    const success = jest.spyOn(toast, 'success');
    openIt();
    cmp.choice.set('s2');
    cmp.note.set(' Fehler im Flow ');
    cmp.submit();
    cmp.submit();
    const post = http.expectOne((r) => r.method === 'POST' && r.url === '/api/applications/app-1/force-status');
    expect(post.request.body).toEqual({ stateId: 's2', note: 'Fehler im Flow' });
    post.flush({ newStateId: 's2', statusEventId: 'e1', dispatchedActions: [] });
    expect(host.open()).toBe(false);
    expect(host.done).toBe(1);
    expect(success).toHaveBeenCalled();
  });

  it.each([
    [403, 'Für diese Aktion fehlt die Berechtigung.'],
    [409, 'conflict'],
    [500, 'error'],
  ])('reports a %s answer and stays open', async (status) => {
    const { http, host, cmp, toast, openIt } = await setup();
    const error = jest.spyOn(toast, 'error');
    openIt();
    cmp.choice.set('s2');
    cmp.note.set('Grund');
    cmp.submit();
    http.expectOne((r) => r.method === 'POST').flush({}, { status, statusText: 'x' });
    expect(cmp.saving()).toBe(false);
    expect(host.open()).toBe(true);
    expect(host.done).toBe(0);
    expect(error).toHaveBeenCalledTimes(1);
  });

  it('closes on "Abbrechen" and starts empty on the next opening', async () => {
    const { http, host, cmp, detectChanges, openIt } = await setup();
    openIt();
    cmp.choice.set('s2');
    cmp.note.set('Grund');
    // The footer button; the close button of the dialog has the same name.
    const cancel = screen.getAllByRole('button', { name: 'Abbrechen' }).find((b) => !b.classList.contains('dialog__close'));
    await userEvent.click(cancel!);
    expect(host.open()).toBe(false);
    host.open.set(true);
    detectChanges();
    expect(cmp.choice()).toBe('');
    expect(cmp.note()).toBe('');
    http.expectOne(STATES_URL).flush({}, { status: 500, statusText: 'x' });
    expect(cmp.options()).toEqual([]);
  });

  it('drops the states of an application it no longer shows', async () => {
    const { http, host, cmp, detectChanges } = await setup();
    host.open.set(true);
    detectChanges();
    const first = http.expectOne(STATES_URL);
    host.id.set('app-2');
    detectChanges();
    first.flush(STATES);
    expect(cmp.options()).toEqual([]);
    http.expectOne((r) => r.url === '/api/applications/app-2/flow-states').flush([STATES[1]]);
    expect(cmp.options().map((o) => o.value)).toEqual(['s2']);
  });

  it('sends nothing without an application', async () => {
    const { http, host, cmp, detectChanges } = await setup();
    host.id.set(null);
    host.open.set(true);
    detectChanges();
    cmp.choice.set('s2');
    cmp.note.set('x');
    cmp.submit();
    http.verify();
  });
});
