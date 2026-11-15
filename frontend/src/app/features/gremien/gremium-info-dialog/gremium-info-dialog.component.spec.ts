import { render } from '@testing-library/angular';
import { throwError } from 'rxjs';
import { GremienApiService } from '@core/api/gremien.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { gremienApiMock, gremiumInfo } from '../../../../testing/gremien-fixtures';
import {
  GremiumInfoDialogComponent,
  draftLinks,
  linkBlank,
  linkErrors,
} from './gremium-info-dialog.component';

const INFO = gremiumInfo({
  bodyMd: 'Hallo',
  links: [
    { label: 'Wiki', url: 'https://wiki.example.org' },
    { label: 'Chat', url: 'https://chat.example.org' },
  ],
  version: 2,
  canEdit: true,
});

async function setup(api = gremienApiMock()) {
  localStorage.setItem('ap.locale', 'de');
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(GremiumInfoDialogComponent, {
    inputs: { open: true, gremiumId: 'g-1', gremiumName: 'STUPA', info: INFO },
    providers: [
      { provide: GremienApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  return { ...view, api, toast, cmp: view.fixture.componentInstance };
}

describe('gremium info drafts', () => {
  const row = (label: string, url: string) => ({ key: 1, label, url });

  it('drops blank rows and trims (§ 000952)', () => {
    expect(linkBlank(row(' ', ''))).toBe(true);
    expect(draftLinks([row(' Wiki ', ' https://w.de '), row('', '')])).toEqual([
      { label: 'Wiki', url: 'https://w.de' },
    ]);
  });

  it('names the error of a row', () => {
    expect(linkErrors(row('', ''))).toEqual({ label: null, url: null });
    expect(linkErrors(row('', 'https://w.de')).label).toBe('gremien.info.labelRequired');
    expect(linkErrors(row('x'.repeat(81), 'https://w.de')).label).toBe('gremien.info.labelTooLong');
    expect(linkErrors(row('Wiki', 'javascript:alert(1)')).url).toBe('gremien.info.urlInvalid');
    expect(linkErrors(row('Mail', 'mailto:a@b.de'))).toEqual({ label: null, url: null });
  });
});

describe('GremiumInfoDialogComponent', () => {
  afterEach(() => localStorage.clear());

  it('starts from the Info and moves, adds and removes links', async () => {
    const { cmp } = await setup();
    expect(cmp.body()).toBe('Hallo');
    expect(cmp.links().map((l) => l.label)).toEqual(['Wiki', 'Chat']);
    cmp.moveLink(1, -1);
    expect(cmp.links().map((l) => l.label)).toEqual(['Chat', 'Wiki']);
    cmp.addLink();
    expect(cmp.links()).toHaveLength(3);
    const key = cmp.links()[2].key;
    cmp.setLabel(key, 'Forum');
    cmp.setUrl(key, 'https://forum.example.org');
    cmp.removeLink(cmp.links()[0].key);
    expect(cmp.links().map((l) => l.label)).toEqual(['Wiki', 'Forum']);
    cmp.setMode('preview');
    expect(cmp.mode()).toBe('preview');
    cmp.setMode(null);
    expect(cmp.mode()).toBe('write');
  });

  it('stops at 30 links', async () => {
    const { cmp } = await setup();
    Array.from({ length: 40 }).forEach(() => cmp.addLink());
    expect(cmp.links()).toHaveLength(30);
    expect(cmp.full()).toBe(true);
  });

  it('saves text and links with the version read (§ 000954)', async () => {
    const { cmp, api, toast } = await setup();
    const saved = jest.fn();
    const closed = jest.fn();
    cmp.saved.subscribe(saved);
    cmp.closed.subscribe(closed);
    cmp.body.set('Neu');
    cmp.save();
    expect(api.saveInfo).toHaveBeenCalledWith('g-1', {
      bodyMd: 'Neu',
      links: [
        { label: 'Wiki', url: 'https://wiki.example.org' },
        { label: 'Chat', url: 'https://chat.example.org' },
      ],
      version: 2,
    });
    expect(saved).toHaveBeenCalled();
    expect(closed).toHaveBeenCalled();
    expect(toast.success).toHaveBeenCalled();
  });

  it('does not save an invalid row and shows its error', async () => {
    const { cmp, api } = await setup();
    cmp.setUrl(cmp.links()[0].key, 'ftp://x');
    expect(cmp.error('gremien.info.urlInvalid')).toBe('');
    cmp.save();
    expect(api.saveInfo).not.toHaveBeenCalled();
    expect(cmp.error(cmp.errors()[0].url)).toContain('https://');
  });

  it('says so on a version conflict and asks the tab to reload', async () => {
    const api = gremienApiMock({
      saveInfo: jest.fn(() =>
        throwError(() => ({ status: 409, error: { code: 'gremium_info_version_conflict' } })),
      ),
    });
    const { cmp, toast } = await setup(api);
    const stale = jest.fn();
    cmp.stale.subscribe(stale);
    cmp.save();
    expect(cmp.conflict()).toBe(true);
    expect(stale).toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('toasts another error and cancels', async () => {
    const api = gremienApiMock({ saveInfo: jest.fn(() => throwError(() => ({ status: 500 }))) });
    const { cmp, toast } = await setup(api);
    const closed = jest.fn();
    cmp.closed.subscribe(closed);
    cmp.save();
    expect(toast.error).toHaveBeenCalled();
    expect(cmp.saving()).toBe(false);
    cmp.cancel();
    expect(closed).toHaveBeenCalled();
  });
});
