import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { AuthService } from '@core/auth/auth.service';
import {
  FEATURES,
  FEATURE_REQUIRES,
  type FeatureKey,
  FeatureService,
} from '@core/features/feature.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { LoadState } from '@shared/forms/settings-form';
import { LoadStateComponent } from '@shared/ui/load-state/load-state.component';
import {
  ButtonComponent,
  ConfirmDialogComponent,
  FabComponent,
  NoteComponent,
  PageHeaderComponent,
  SwitchComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';
import { AdminApiService } from '../admin-api.service';
import type { FeatureSwitches } from '../admin.models';

/** The name of each feature, as the navigation shows it. */
export const FEATURE_LABELS: Readonly<Record<FeatureKey, TranslationKey>> = {
  todos: 'nav.todos',
  calendar: 'nav.calendar',
  meetings: 'nav.meetings',
  voting: 'nav.voting',
  budget: 'nav.budget',
  invoices: 'nav.invoices',
  tickets: 'nav.tickets',
};

/** One place that still needs a feature, from the 409 `feature_in_use` of the save. */
export interface FeatureUse {
  readonly feature: FeatureKey;
  readonly kind: 'state' | 'transition' | 'type';
  readonly name: string;
}

/** The text of a use, by its kind. */
const USE_TEXT: Readonly<Record<FeatureUse['kind'], TranslationKey>> = {
  state: 'admin.features.use.state',
  transition: 'admin.features.use.transition',
  type: 'admin.features.use.type',
};

/** The switches with every feature on: the state of a config without an entry. */
const ALL_ON: FeatureSwitches = {
  todos: true,
  calendar: true,
  meetings: true,
  voting: true,
  budget: true,
  invoices: true,
  tickets: true,
};

/** The features that are on: the own switch and each needed feature is on. */
export function enabledFeatures(switches: FeatureSwitches): Readonly<Record<FeatureKey, boolean>> {
  return Object.fromEntries(
    FEATURES.map((key) => [
      key,
      switches[key] && (FEATURE_REQUIRES[key] ?? []).every((needed) => switches[needed]),
    ]),
  ) as Record<FeatureKey, boolean>;
}

/** Read the uses of the problem body of a 409 `feature_in_use`. Unknown entries drop out. */
export function usesOf(errors: unknown): readonly FeatureUse[] {
  const list: readonly unknown[] = Array.isArray(errors) ? errors : [];
  return list.flatMap((entry) => {
    const { field, msg } = (entry ?? {}) as { field?: unknown; msg?: unknown };
    const [kind, ...rest] = typeof msg === 'string' ? msg.split(':') : [];
    const feature = FEATURES.find((key) => key === field);
    return feature && (kind === 'state' || kind === 'transition' || kind === 'type')
      ? [{ feature, kind, name: rest.join(':') }]
      : [];
  });
}

/**
 * "Funktionen" (permission `admin.features`): one switch for each feature of the platform.
 *
 * `GET/PUT /admin/features` reads and saves the switches. A feature that is off does not
 * show in the UI and its API answers 404; its data stays. A switch of a feature that needs
 * a feature that is off is locked and says which one: `Rechnungen` needs `Budget`. The
 * stored switch stays, so it returns when the other feature goes on again.
 *
 * "Speichern" (the floating button) and "Verwerfen" (in the header) show only while a
 * switch differs. A save that switches a feature off asks first and names the features. The
 * server refuses to switch off a feature that the Antrag flow or an Antragsart uses (409
 * `feature_in_use`); the page then names each use. After a save the navigation follows the
 * new switches at once.
 */
@Component({
  selector: 'app-admin-features',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    PageHeaderComponent,
    BreadcrumbsComponent,
    ButtonComponent,
    ConfirmDialogComponent,
    FabComponent,
    LoadStateComponent,
    NoteComponent,
    SwitchComponent,
  ],
  templateUrl: './features.component.html',
  styleUrl: './features.component.scss',
})
export class FeaturesComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly features = inject(FeatureService);

  protected readonly keys = FEATURES;
  protected readonly labels = FEATURE_LABELS;

  private readonly loading = signal(true);
  private readonly loadState = signal<Exclude<LoadState, 'loading'>>('ok');
  protected readonly state = computed<LoadState>(() =>
    this.loading() ? 'loading' : this.loadState(),
  );
  protected readonly saving = signal(false);
  private readonly saved = signal<FeatureSwitches | null>(null);
  protected readonly draft = signal<FeatureSwitches>(ALL_ON);
  /** The save waits for the answer of the confirmation. */
  protected readonly confirming = signal(false);
  /** The uses that the server named when it refused the last save. */
  protected readonly uses = signal<readonly FeatureUse[]>([]);

  protected readonly dirty = computed(() => {
    const saved = this.saved();
    const draft = this.draft();
    return saved !== null && FEATURES.some((key) => saved[key] !== draft[key]);
  });

  /** The feature that locks each switch: the first needed feature that is off. */
  protected readonly lockedBy = computed<Readonly<Partial<Record<FeatureKey, FeatureKey>>>>(() => {
    const draft = this.draft();
    return Object.fromEntries(
      FEATURES.flatMap((key) => {
        const missing = (FEATURE_REQUIRES[key] ?? []).find((needed) => !draft[needed]);
        return missing ? [[key, missing]] : [];
      }),
    );
  });

  /** The features that the save switches off, by name. */
  protected readonly goingOff = computed(() => {
    const saved = this.saved();
    const before = enabledFeatures(saved ?? ALL_ON);
    const after = enabledFeatures(this.draft());
    return FEATURES.filter((key) => before[key] && !after[key]).map((key) =>
      this.i18n.translate(FEATURE_LABELS[key]),
    );
  });

  protected readonly confirmBody = computed(() =>
    this.i18n.translate('admin.features.confirm', { names: this.goingOff().join(', ') }),
  );

  constructor() {
    if (this.auth.can('admin.features')) {
      this.load();
    } else {
      this.loading.set(false);
      this.loadState.set('forbidden');
    }
  }

  protected load(): void {
    this.loading.set(true);
    this.api.getFeatures().subscribe({
      next: (switches) => {
        this.apply(switches);
        this.loading.set(false);
        this.loadState.set('ok');
      },
      error: (err: { status?: number } | null) => {
        this.loading.set(false);
        this.loadState.set(err?.status === 403 ? 'forbidden' : 'error');
      },
    });
  }

  private apply(switches: FeatureSwitches): void {
    this.saved.set(switches);
    this.draft.set(switches);
    this.uses.set([]);
  }

  /** A switch shows off while a feature it needs is off; its stored value stays. */
  protected shown(key: FeatureKey): boolean {
    return this.draft()[key] && !this.lockedBy()[key];
  }

  protected hint(key: FeatureKey): string {
    const by = this.lockedBy()[key];
    return by
      ? this.i18n.translate('admin.features.needs', {
          name: this.i18n.translate(FEATURE_LABELS[by]),
        })
      : '';
  }

  protected set(key: FeatureKey, on: boolean): void {
    this.draft.update((d) => ({ ...d, [key]: on }));
  }

  protected useText(use: FeatureUse): string {
    return this.i18n.translate(USE_TEXT[use.kind], {
      feature: this.i18n.translate(FEATURE_LABELS[use.feature]),
      name: use.name,
    });
  }

  protected discard(): void {
    const saved = this.saved();
    if (saved) this.apply(saved);
  }

  /** A save that switches a feature off asks first. */
  protected save(): void {
    if (!this.dirty() || this.saving()) return;
    if (this.goingOff().length) this.confirming.set(true);
    else this.send();
  }

  protected confirmed(): void {
    this.confirming.set(false);
    this.send();
  }

  private send(): void {
    this.saving.set(true);
    this.api.putFeatures(this.draft()).subscribe({
      next: (switches) => {
        this.saving.set(false);
        this.apply(switches);
        this.features.saved(enabledFeatures(switches));
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: (err: { status?: number; error?: { code?: string; errors?: unknown } } | null) => {
        this.saving.set(false);
        const inUse = err?.status === 409 && err.error?.code === 'feature_in_use';
        this.uses.set(inUse ? usesOf(err.error?.errors) : []);
        this.toast.error(
          this.i18n.translate(inUse ? 'admin.features.inUse' : 'admin.common.saveFailed'),
        );
      },
    });
  }
}
