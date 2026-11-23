import { TestBed } from '@angular/core/testing';
import { render } from '@testing-library/angular';
import { Subject, of, throwError } from 'rxjs';
import { LIVE_SEARCH_DEBOUNCE_MS, ToastService } from '@stupa-makers/ui-kit';
import { PaperlessService, type PaperlessCopy, type PaperlessHit } from '@core/api/paperless.service';
import { kindSpies } from '../../../../testing/toast';
import { PaperlessInsertComponent, paperlessInsertErrorKey } from './paperless-insert.component';

const HITS: PaperlessHit[] = [
  { documentId: 418, title: 'Angebot Beamer', documentType: 'Angebot', created: '2026-11-18' },
  { documentId: 417, title: 'Bescheid', documentType: null, created: null },
];
const COPY: PaperlessCopy = { name: 'Angebot Beamer.pdf', url: '/api/media/documents/d1' };

async function setup(api: Partial<Record<'search' | 'insert', jest.Mock>> = {}) {
  const search = api.search ?? jest.fn(() => of(HITS));
  const insert = api.insert ?? jest.fn(() => of(COPY));
  const inserted = jest.fn();
  const view = await render(PaperlessInsertComponent, {
    inputs: { meetingId: 'm1', open: false },
    on: { inserted },
    providers: [{ provide: PaperlessService, useValue: { search, insert } }],
  });
  const toast = kindSpies(TestBed.inject(ToastService));
  const show = async (): Promise<void> => {
    view.fixture.componentRef.setInput('open', true);
    view.fixture.detectChanges();
    await new Promise((r) => setTimeout(r, 0));
    view.fixture.detectChanges();
  };
  const field = (): HTMLInputElement => document.querySelector('.sw__input') as HTMLInputElement;
  const titles = (): (string | null | undefined)[] =>
    [...document.querySelectorAll('.sw__rowTitle')].map((n) => n.textContent);
  const key = (name: string): void => {
    field().dispatchEvent(new KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true }));
    view.fixture.detectChanges();
  };
  return { ...view, search, insert, inserted, toast, show, field, titles, key };
}

/** § F/integrations/paperless/002534, 002528, 002529: the Paperless search of a protocol text. */
describe('PaperlessInsertComponent', () => {
  afterEach(() => document.querySelectorAll('.sw-layer').forEach((n) => n.remove()));

  it('opens with the newest documents and shows title, type and date', async () => {
    const { show, search, titles } = await setup();
    expect(search).not.toHaveBeenCalled();
    await show();
    expect(search).toHaveBeenCalledTimes(1);
    expect(search).toHaveBeenCalledWith('');
    expect(titles()).toEqual(['Angebot Beamer', 'Bescheid']);
    const subs = [...document.querySelectorAll('.sw__row')].map((r) => r.querySelector('.sw__rowSub')?.textContent);
    expect(subs).toEqual(['Angebot · 18.11.2026', undefined]);
    expect(document.querySelector('.sw')?.getAttribute('aria-label')).toBe('In Paperless suchen');
  });

  it('searches the typed text after the debounce', async () => {
    jest.useFakeTimers();
    try {
      const { fixture, search, field } = await setup();
      fixture.componentRef.setInput('open', true);
      fixture.detectChanges();
      jest.advanceTimersByTime(0);
      field().value = 'beamer';
      field().dispatchEvent(new Event('input'));
      jest.advanceTimersByTime(LIVE_SEARCH_DEBOUNCE_MS);
      expect(search).toHaveBeenLastCalledWith('beamer');
    } finally {
      jest.useRealTimers();
    }
  });

  it('closes with the key Esc and copies nothing', async () => {
    const { show, key, insert, fixture } = await setup();
    await show();
    key('Escape');
    expect(fixture.componentInstance.open()).toBe(false);
    expect(document.querySelector('.sw')).toBeNull();
    expect(insert).not.toHaveBeenCalled();
  });

  it('copies the hit that Enter picks, emits the copy and closes', async () => {
    const { show, key, insert, inserted, fixture } = await setup();
    await show();
    key('ArrowDown');
    key('Enter');
    expect(insert).toHaveBeenCalledWith('m1', 417);
    expect(inserted).toHaveBeenCalledWith(COPY);
    expect(fixture.componentInstance.open()).toBe(false);
  });

  it('runs one copy at a time', async () => {
    const pending = new Subject<PaperlessCopy>();
    const insert = jest.fn(() => pending);
    const { show, key, inserted } = await setup({ insert });
    await show();
    key('Enter');
    key('Enter');
    expect(insert).toHaveBeenCalledTimes(1);
    pending.next(COPY);
    expect(inserted).toHaveBeenCalledTimes(1);
  });

  it('names a failed copy and stays open', async () => {
    const insert = jest.fn(() => throwError(() => ({ status: 415 })));
    const { show, key, inserted, toast, fixture } = await setup({ insert });
    await show();
    key('Enter');
    expect(toast.error).toHaveBeenCalledWith('Dieses Dokument hat keine lesbare PDF-Fassung.');
    expect(inserted).not.toHaveBeenCalled();
    expect(fixture.componentInstance.open()).toBe(true);
  });

  it('tells an outage of Paperless in the window', async () => {
    const search = jest.fn(() => throwError(() => ({ status: 503 })));
    const { show, titles } = await setup({ search });
    await show();
    expect(document.querySelector('.sw__note')?.textContent).toBe('Paperless ist nicht erreichbar');
    expect(titles()).toEqual([]);
  });

  it('shows the empty state without a hit', async () => {
    const { show } = await setup({ search: jest.fn(() => of([])) });
    await show();
    expect(document.querySelector('app-empty-state')?.textContent).toContain('Keine Dokumente gefunden');
  });

  it('maps each status of a failed copy to its text', () => {
    expect(paperlessInsertErrorKey(403)).toBe('paperless.insert.error.forbidden');
    expect(paperlessInsertErrorKey(413)).toBe('paperless.insert.error.tooLarge');
    expect(paperlessInsertErrorKey(415)).toBe('paperless.insert.error.type');
    expect(paperlessInsertErrorKey(503)).toBe('paperless.insert.error.unavailable');
    expect(paperlessInsertErrorKey(500)).toBe('paperless.insert.error.failed');
    expect(paperlessInsertErrorKey()).toBe('paperless.insert.error.failed');
  });
});
