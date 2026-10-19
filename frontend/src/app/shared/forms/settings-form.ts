import { computed, inject, type Signal, signal, type WritableSignal } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService } from '@stupa-makers/ui-kit';
import type { Observable } from 'rxjs';

/** The state of a page or a section that reads its data first. */
export type LoadState = 'loading' | 'ok' | 'forbidden' | 'error';

/** What {@link settingsForm} needs from the page. */
export interface SettingsFormOptions<S, D, B> {
  /** The read of the stored settings. */
  load: () => Observable<S>;
  /** The write. The answer is the new stored state. */
  put: (body: B) => Observable<S>;
  /** The draft of a stored state. The fields hold the text of the inputs. */
  draftOf: (saved: S) => D;
  /** The draft before the read answers. */
  initial: D;
  /**
   * The body of the write, or `null` while a field is invalid. It may read the `draft`
   * of the form and the page's own signals; the form calls it only inside a computed.
   */
  body: () => B | null;
  /** The body sends the stored values again. Without it the form compares by `dirty`. */
  unchanged?: (body: B, saved: S) => boolean;
  /**
   * The draft differs from the stored values. Default: an invalid body is a change, else
   * the body is not `unchanged`.
   */
  dirty?: (saved: S) => boolean;
  /** The right the page needs. Without it the form does not read and shows `forbidden`. */
  allowed?: () => boolean;
  /** Called after each read and each write with the stored state. */
  onApply?: (saved: S) => void;
}

/** The state and the actions of a settings form. Make it with {@link settingsForm}. */
export interface SettingsForm<S, D> {
  /** `loading` until the read answers, then `ok`, `forbidden` (no right or 403) or `error`. */
  readonly state: Signal<LoadState>;
  readonly loading: Signal<boolean>;
  readonly saving: Signal<boolean>;
  /** The stored values; the draft compares against them. */
  readonly saved: Signal<S | null>;
  readonly draft: WritableSignal<D>;
  readonly dirty: Signal<boolean>;
  /** Every field is valid. */
  readonly valid: Signal<boolean>;
  /** A change that is valid and no write is running. */
  readonly canSave: Signal<boolean>;
  /** Merge a change into the draft. */
  patch(change: Partial<D>): void;
  /** Put the stored values back into the draft. */
  reset(): void;
  /** Send the draft. A toast names the result. */
  save(): void;
}

/**
 * The logic of a settings page or section: read once, edit a draft, save with a toast.
 *
 * A settings page reads its values (`GET`), keeps a draft of the inputs and compares it
 * with the stored values. "Speichern" sends the draft (`PUT`); the answer is the new
 * stored state, and a toast says "Gespeichert" or "Speichern fehlgeschlagen". Without the
 * right, or after a 403 on the read, the state is `forbidden`, so a person without the
 * right never sees a form that the server refuses. `app-load-state` shows the states.
 *
 * Call it in an injection context (a field initializer). The read starts at once.
 *
 * ```ts
 * protected readonly form = settingsForm<LoginSettings, Draft, Body>({
 *   allowed: () => this.auth.can('admin.users'),
 *   load: () => this.api.getLoginSettings(),
 *   put: (b) => this.api.putLoginSettings(b),
 *   draftOf, initial: { web: '', pwa: '' },
 *   body: () => this.body(),
 *   unchanged: (b, s) => b.webSessionDays === s.webSessionDays,
 * });
 * ```
 */
export function settingsForm<S, D extends object, B>(opts: SettingsFormOptions<S, D, B>): SettingsForm<S, D> {
  const i18n = inject(I18nService);
  const toast = inject(ToastService);

  const loading = signal(true);
  const loadState = signal<Exclude<LoadState, 'loading'>>('ok');
  const saving = signal(false);
  const saved = signal<S | null>(null);
  const draft = signal<D>(opts.initial);

  const dirty = computed(() => {
    const s = saved();
    if (!s) return false;
    if (opts.dirty) return opts.dirty(s);
    const b = opts.body();
    if (b === null) return true;
    return !opts.unchanged?.(b, s);
  });
  const valid = computed(() => opts.body() !== null);
  const canSave = computed(() => dirty() && valid() && !saving());

  const apply = (s: S): void => {
    saved.set(s);
    draft.set(opts.draftOf(s));
    opts.onApply?.(s);
    loading.set(false);
    loadState.set('ok');
  };

  if (opts.allowed && !opts.allowed()) {
    loading.set(false);
    loadState.set('forbidden');
  } else {
    opts.load().subscribe({
      next: apply,
      error: (err: { status?: number } | null) => {
        loading.set(false);
        loadState.set(err?.status === 403 ? 'forbidden' : 'error');
      },
    });
  }

  return {
    state: computed(() => (loading() ? 'loading' : loadState())),
    loading: loading.asReadonly(),
    saving: saving.asReadonly(),
    saved: saved.asReadonly(),
    draft,
    dirty,
    valid,
    canSave,
    patch: (change) => draft.update((d) => ({ ...d, ...change })),
    reset: () => {
      const s = saved();
      if (s) apply(s);
    },
    save: () => {
      const body = opts.body();
      if (body === null || !canSave()) return;
      saving.set(true);
      opts.put(body).subscribe({
        next: (s) => {
          saving.set(false);
          apply(s);
          toast.success(i18n.translate('admin.common.saved'));
        },
        error: () => {
          saving.set(false);
          toast.error(i18n.translate('admin.common.saveFailed'));
        },
      });
    },
  };
}
