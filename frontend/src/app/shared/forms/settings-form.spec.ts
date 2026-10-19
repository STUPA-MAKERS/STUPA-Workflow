import { computed, Injector, runInInjectionContext, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ToastService } from '@stupa-makers/ui-kit';
import { type Observable, of, Subject, throwError } from 'rxjs';
import { settingsForm, type SettingsFormOptions } from './settings-form';

interface Stored {
  days: number;
}
interface Draft {
  days: string;
}

describe('settingsForm', () => {
  const toast = { success: jest.fn(), error: jest.fn() };

  beforeEach(() => {
    toast.success.mockReset();
    toast.error.mockReset();
    TestBed.configureTestingModule({ providers: [{ provide: ToastService, useValue: toast }] });
  });

  function make(over: Partial<SettingsFormOptions<Stored, Draft, Stored>> = {}) {
    const injector = Injector.create({ providers: [], parent: TestBed.inject(Injector) });
    const put = jest.fn((b: Stored): Observable<Stored> => of(b));
    return runInInjectionContext(injector, () => {
      const holder: { body?: () => Stored | null } = {};
      const form = settingsForm<Stored, Draft, Stored>({
        load: () => of({ days: 5 }),
        put,
        draftOf: (s) => ({ days: String(s.days) }),
        initial: { days: '' },
        body: () => holder.body!(),
        unchanged: (b, s) => b.days === s.days,
        ...over,
      });
      const body = computed(() => {
        const n = Number(form.draft().days);
        return Number.isInteger(n) && n > 0 && form.draft().days.trim() !== '' ? { days: n } : null;
      });
      holder.body = body;
      return { form, put };
    });
  }

  it('reads the stored values into the draft', () => {
    const { form } = make();
    expect(form.state()).toBe('ok');
    expect(form.draft()).toEqual({ days: '5' });
    expect(form.dirty()).toBe(false);
    expect(form.canSave()).toBe(false);
  });

  it('is loading until the read answers', () => {
    const read = new Subject<Stored>();
    const { form } = make({ load: () => read });
    expect(form.state()).toBe('loading');
    expect(form.dirty()).toBe(false);
    read.next({ days: 2 });
    expect(form.state()).toBe('ok');
  });

  it('is forbidden without the right and does not read', () => {
    const load = jest.fn(() => of({ days: 1 }));
    const { form } = make({ allowed: () => false, load });
    expect(form.state()).toBe('forbidden');
    expect(load).not.toHaveBeenCalled();
  });

  it('is forbidden after a 403 and an error after another failure', () => {
    expect(make({ load: () => throwError(() => ({ status: 403 })) }).form.state()).toBe('forbidden');
    expect(make({ load: () => throwError(() => ({ status: 500 })) }).form.state()).toBe('error');
    expect(make({ load: () => throwError(() => null) }).form.state()).toBe('error');
  });

  it('counts a change, and an invalid field, as dirty', () => {
    const { form } = make();
    form.patch({ days: '7' });
    expect(form.dirty()).toBe(true);
    expect(form.canSave()).toBe(true);
    form.patch({ days: 'x' });
    expect(form.dirty()).toBe(true);
    expect(form.valid()).toBe(false);
    expect(form.canSave()).toBe(false);
    form.patch({ days: '5' });
    expect(form.dirty()).toBe(false);
  });

  it('saves the body, takes the answer as the new baseline and toasts', () => {
    const { form, put } = make();
    form.patch({ days: '9' });
    form.save();
    expect(put).toHaveBeenCalledWith({ days: 9 });
    expect(form.saved()).toEqual({ days: 9 });
    expect(form.dirty()).toBe(false);
    expect(form.saving()).toBe(false);
    expect(toast.success).toHaveBeenCalledWith('Gespeichert.');
  });

  it('does not save an unchanged or invalid draft, nor twice at once', () => {
    const answer = new Subject<Stored>();
    const put = jest.fn(() => answer);
    const { form } = make({ put });
    form.save();
    form.patch({ days: 'x' });
    form.save();
    expect(put).not.toHaveBeenCalled();
    form.patch({ days: '3' });
    form.save();
    form.save();
    expect(put).toHaveBeenCalledTimes(1);
    expect(form.saving()).toBe(true);
  });

  it('toasts a failed save and keeps the draft', () => {
    const { form } = make({ put: () => throwError(() => new Error('x')) });
    form.patch({ days: '8' });
    form.save();
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
    expect(form.draft()).toEqual({ days: '8' });
    expect(form.dirty()).toBe(true);
    expect(form.saving()).toBe(false);
  });

  it('puts the stored values back on a reset and calls onApply', () => {
    const onApply = jest.fn();
    const { form } = make({ onApply });
    form.patch({ days: '1' });
    form.reset();
    expect(form.draft()).toEqual({ days: '5' });
    expect(onApply).toHaveBeenCalledTimes(2);
  });

  it('ignores a reset before the read', () => {
    const { form } = make({ load: () => new Subject<Stored>() });
    form.reset();
    expect(form.draft()).toEqual({ days: '' });
  });

  it('takes a dirty rule of the page', () => {
    const touched = signal(false);
    const { form } = make({ dirty: () => touched() });
    expect(form.dirty()).toBe(false);
    touched.set(true);
    expect(form.dirty()).toBe(true);
  });

  it('treats a body without an unchanged rule as a change', () => {
    const { form } = make({ unchanged: undefined });
    expect(form.dirty()).toBe(true);
  });
});
