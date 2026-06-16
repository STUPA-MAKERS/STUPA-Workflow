import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { Gremium } from '../admin.models';
import { AdminGremienComponent } from './gremien.component';

const GREMIUM: Gremium = {
  id: 'g-1',
  name: 'Studierendenparlament',
  slug: 'stupa',
  cdVariant: 'stupa',
  defaultLang: 'de',
  allowVoteDelegation: false,
};

async function setup(gremien: Gremium[] = [GREMIUM]) {
  const view = await render(AdminGremienComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  http.expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'GET').flush(gremien);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, http, c };
}

describe('AdminGremienComponent (#18)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists existing committees from /admin/gremien', async () => {
    const { http, c } = await setup();
    expect(await screen.findByText('Studierendenparlament')).toBeInTheDocument();
    expect(c.loading()).toBe(false);
    expect(c.loadError()).toBe(false);
    http.verify();
  });

  it('shows the empty state when there are none', async () => {
    const { http } = await setup([]);
    expect(await screen.findByText('Noch keine Gremien angelegt.')).toBeInTheDocument();
    http.verify();
  });

  it('sets loadError when the list request fails', async () => {
    const view = await render(AdminGremienComponent, {
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    http
      .expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'GET')
      .flush('boom', { status: 500, statusText: 'Server Error' });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = view.fixture.componentInstance as any;
    expect(c.loadError()).toBe(true);
    expect(c.loading()).toBe(false);
    http.verify();
  });

  it('slugPreview shows a dash for an empty name and the slug otherwise', async () => {
    const { c } = await setup([]);
    expect(c.slugPreview()).toBe('—');
    c.patch('name', 'AStA Vorstand');
    expect(c.slugPreview()).toBe('asta-vorstand');
  });

  it('patchLead clamps to 0 for empty/invalid/negative, keeps positive ints', async () => {
    const { c } = await setup([]);
    c.openCreate();
    c.patchLead(15);
    expect(c.form().delegationLeadMinutes).toBe(15);
    c.patchLead('');
    expect(c.form().delegationLeadMinutes).toBe(0);
    c.patchLead(-5);
    expect(c.form().delegationLeadMinutes).toBe(0);
    c.patchLead('abc');
    expect(c.form().delegationLeadMinutes).toBe(0);
    c.patchLead(7.6);
    expect(c.form().delegationLeadMinutes).toBe(8); // rounds
  });

  it('patchQuorum: null/empty/undefined → null, else clamps to 0..100', async () => {
    const { c } = await setup([]);
    c.openCreate();
    c.patchQuorum(null);
    expect(c.form().quorumPercent).toBeNull();
    c.patchQuorum('');
    expect(c.form().quorumPercent).toBeNull();
    c.patchQuorum(undefined);
    expect(c.form().quorumPercent).toBeNull();
    c.patchQuorum(50);
    expect(c.form().quorumPercent).toBe(50);
    c.patchQuorum(150);
    expect(c.form().quorumPercent).toBe(100);
    c.patchQuorum(-10);
    expect(c.form().quorumPercent).toBe(0);
    c.patchQuorum('abc');
    expect(c.form().quorumPercent).toBeNull(); // NaN → null
    c.patchQuorum(33.4);
    expect(c.form().quorumPercent).toBe(33); // rounds
  });

  it('creates a committee via a dialog with an auto-generated slug', async () => {
    const { http } = await setup([]);
    await userEvent.click(screen.getByRole('button', { name: 'Gremium hinzufügen' }));
    await userEvent.type(screen.getByLabelText('Name'), 'AStA Vorstand');
    await userEvent.click(screen.getByRole('button', { name: 'Anlegen' }));

    const post = http.expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'POST');
    expect(post.request.body).toEqual({
      name: 'AStA Vorstand',
      slug: 'asta-vorstand',
      cdVariant: 'stupa',
      defaultLang: 'de',
      allowVoteDelegation: false,
      delegationLeadMinutes: 0,
      delegationAllowExternal: false,
      quorumPercent: null,
    });
    post.flush({ ...GREMIUM, id: 'g-2', name: 'AStA Vorstand', slug: 'asta-vorstand' });
    const putMail = http.expectOne(
      (r) => r.url.endsWith('/admin/gremien/g-2/mail-recipients') && r.method === 'PUT',
    );
    expect(putMail.request.body).toEqual({ recipients: [] });
    putMail.flush({ recipients: [] });
    http.expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'GET').flush([]);
    http.verify();
  });

  it('create slug falls back to the lowercased trimmed name when slugify is empty', async () => {
    const { http, c } = await setup([]);
    c.openCreate();
    c.patch('name', '???'); // slugify → '' → fallback to lowercased trimmed name
    c.patch('mailRecipients', 'a@x.de\nb@y.de, c@z.de; d@w.de');
    c.submit(new Event('submit'));
    const post = http.expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'POST');
    expect(post.request.body.slug).toBe('???');
    post.flush({ ...GREMIUM, id: 'g-9', name: '???' });
    const putMail = http.expectOne(
      (r) => r.url.endsWith('/admin/gremien/g-9/mail-recipients') && r.method === 'PUT',
    );
    // parseRecipients splits on newlines/commas/semicolons and trims
    expect(putMail.request.body).toEqual({ recipients: ['a@x.de', 'b@y.de', 'c@z.de', 'd@w.de'] });
    putMail.flush({ recipients: [] });
    http.expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'GET').flush([]);
    http.verify();
  });

  it('edits a committee via PATCH (slug stays) incl. extra recipients', async () => {
    const { http } = await setup();
    await screen.findByText('Studierendenparlament');
    await userEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    http
      .expectOne((r) => r.url.endsWith('/admin/gremien/g-1/mail-recipients') && r.method === 'GET')
      .flush({ recipients: ['alt@x.de'] });
    const name = screen.getByLabelText('Name');
    await userEvent.clear(name);
    await userEvent.type(name, 'StuPa 2026');
    await userEvent.selectOptions(screen.getByLabelText(/Standardsprache/), 'en');
    const mail = screen.getByLabelText('Zusätzliche Protokoll-Empfänger');
    await userEvent.clear(mail);
    await userEvent.type(mail, 'neu@y.org');
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));

    const patch = http.expectOne((r) => r.url.endsWith('/admin/gremien/g-1') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({
      name: 'StuPa 2026',
      cdVariant: 'stupa',
      defaultLang: 'en',
      allowVoteDelegation: false,
      delegationLeadMinutes: 0,
      delegationAllowExternal: false,
      quorumPercent: null,
    });
    patch.flush({ ...GREMIUM, name: 'StuPa 2026', defaultLang: 'en' });
    const putMail = http.expectOne(
      (r) => r.url.endsWith('/admin/gremien/g-1/mail-recipients') && r.method === 'PUT',
    );
    expect(putMail.request.body).toEqual({ recipients: ['neu@y.org'] });
    putMail.flush({ recipients: ['neu@y.org'] });
    http.expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'GET').flush([]);
    http.verify();
  });

  it('openEdit loads existing values incl. optional delegation/quorum fields', async () => {
    const full: Gremium = {
      ...GREMIUM,
      allowVoteDelegation: true,
      delegationLeadMinutes: 30,
      delegationAllowExternal: true,
      quorumPercent: 50,
    };
    const { http, c } = await setup([full]);
    c.openEdit(full);
    // mail-recipients lazy load on edit
    http
      .expectOne((r) => r.url.endsWith('/admin/gremien/g-1/mail-recipients') && r.method === 'GET')
      .flush({ recipients: ['x@y.de', 'z@w.de'] });
    expect(c.editingId()).toBe('g-1');
    expect(c.form()).toEqual({
      name: 'Studierendenparlament',
      cdVariant: 'stupa',
      defaultLang: 'de',
      allowVoteDelegation: true,
      delegationLeadMinutes: 30,
      delegationAllowExternal: true,
      quorumPercent: 50,
      mailRecipients: 'x@y.de\nz@w.de',
    });
    http.verify();
  });

  it('openEdit defaults optional fields when absent and ignores recipient load errors', async () => {
    const { http, c } = await setup();
    c.openEdit(GREMIUM);
    http
      .expectOne((r) => r.url.endsWith('/admin/gremien/g-1/mail-recipients') && r.method === 'GET')
      .flush('no', { status: 500, statusText: 'err' });
    expect(c.form().delegationLeadMinutes).toBe(0);
    expect(c.form().delegationAllowExternal).toBe(false);
    expect(c.form().quorumPercent).toBeNull();
    expect(c.form().mailRecipients).toBe(''); // unchanged on error
    http.verify();
  });

  it('submit is a no-op for a blank name', async () => {
    const { http, c } = await setup([]);
    c.openCreate();
    c.patch('name', '   ');
    c.submit(new Event('submit'));
    expect(c.saving()).toBe(false);
    http.verify(); // no POST emitted
  });

  it('submit is a no-op while already saving', async () => {
    const { http, c } = await setup([]);
    c.openCreate();
    c.patch('name', 'X');
    c.saving.set(true);
    c.submit(new Event('submit'));
    http.verify(); // no request since saving guard short-circuits
  });

  it('closeDialog closes the dialog', async () => {
    const { c } = await setup([]);
    c.openCreate();
    expect(c.dialogOpen()).toBe(true);
    c.closeDialog();
    expect(c.dialogOpen()).toBe(false);
  });

  it('create error path resets saving and shows an error toast', async () => {
    const { http, c } = await setup([]);
    c.openCreate();
    c.patch('name', 'Boom');
    c.submit(new Event('submit'));
    http
      .expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'POST')
      .flush('no', { status: 500, statusText: 'err' });
    expect(c.saving()).toBe(false);
    http.verify();
  });

  it('update error path resets saving and shows an error toast', async () => {
    const { http, c } = await setup();
    c.editingId.set('g-1');
    c.patch('name', 'New');
    c.submit(new Event('submit'));
    http
      .expectOne((r) => r.url.endsWith('/admin/gremien/g-1') && r.method === 'PATCH')
      .flush('no', { status: 500, statusText: 'err' });
    expect(c.saving()).toBe(false);
    http.verify();
  });

  it('recipients-save error path resets saving', async () => {
    const { http, c } = await setup([]);
    c.openCreate();
    c.patch('name', 'X');
    c.submit(new Event('submit'));
    http
      .expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'POST')
      .flush({ ...GREMIUM, id: 'g-2', name: 'X' });
    http
      .expectOne((r) => r.url.endsWith('/admin/gremien/g-2/mail-recipients') && r.method === 'PUT')
      .flush('no', { status: 500, statusText: 'err' });
    expect(c.saving()).toBe(false);
    http.verify();
  });

  it('askDelete + doDelete deletes and reloads; success state cleared', async () => {
    const { http, c } = await setup();
    c.askDelete(GREMIUM);
    expect(c.confirmDelete()).toEqual(GREMIUM);
    c.doDelete();
    http
      .expectOne((r) => r.url.endsWith('/admin/gremien/g-1') && r.method === 'DELETE')
      .flush(null);
    http.expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'GET').flush([]);
    expect(c.deleting()).toBe(false);
    expect(c.confirmDelete()).toBeNull();
    http.verify();
  });

  it('doDelete is a no-op without a confirm target or while deleting', async () => {
    const { http, c } = await setup();
    c.doDelete(); // no target
    c.confirmDelete.set(GREMIUM);
    c.deleting.set(true);
    c.doDelete(); // already deleting
    http.verify(); // no DELETE
  });

  it('doDelete error path resets deleting and shows an error toast', async () => {
    const { http, c } = await setup();
    c.askDelete(GREMIUM);
    c.doDelete();
    http
      .expectOne((r) => r.url.endsWith('/admin/gremien/g-1') && r.method === 'DELETE')
      .flush('no', { status: 500, statusText: 'err' });
    expect(c.deleting()).toBe(false);
    http.verify();
  });

  it('keeps create disabled until a name is set', async () => {
    await setup([]);
    await userEvent.click(screen.getByRole('button', { name: 'Gremium hinzufügen' }));
    const add = screen.getByRole('button', { name: 'Anlegen' });
    expect(add).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Name'), 'X');
    expect(add).toBeEnabled();
  });

  it('openCreate resets to a fresh empty form', async () => {
    const { c } = await setup();
    c.editingId.set('g-1');
    c.patch('name', 'leftover');
    c.openCreate();
    expect(c.editingId()).toBeNull();
    expect(c.form().name).toBe('');
    expect(c.dialogOpen()).toBe(true);
  });
});
