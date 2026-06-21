import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import {
  BadgeComponent,
  ButtonComponent,
  DialogComponent,
  IconComponent,
  SelectComponent,
  type SelectOption,
} from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import {
  type AccountOption,
  type BankSyncResult,
  BudgetTreeApi,
  type StatementLine,
  flattenBudgetOptions,
} from '../budget/budget-tree.api';

/**
 * Bank-Abgleich-Dialog (#fints): Kontoumsätze per **FinTS** abrufen (Option A) oder aus
 * einer **CAMT.053/MT940-Datei** importieren (Option D), dann gestaget abgleichen — je
 * Umsatz eine Kostenstelle wählen und buchen (oder ignorieren).
 *
 * FinTS verlangt eine TAN (PSD2/SCA): der Server pausiert den Dialog und liefert eine
 * Challenge; der Nutzer gibt die TAN ein (oder gibt bei *decoupled* pushTAN in der Banking-
 * App frei und pollt). Self-contained: lädt Konten/Baum/Umsätze selbst; meldet `changed`,
 * damit die Buchungsliste neu lädt.
 */
@Component({
  selector: 'app-bank-import-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    BadgeComponent,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    SelectComponent,
  ],
  templateUrl: './bank-import-dialog.component.html',
  styleUrl: './bank-import-dialog.component.scss',
})
export class BankImportDialogComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  /** Sichtbarkeit (vom Eltern-Tab gesteuert). */
  readonly open = input(false);
  /** Dialog geschlossen. */
  readonly closed = output<void>();
  /** Es wurde gebucht/ignoriert → Buchungsliste im Eltern-Tab neu laden. */
  readonly changed = output<void>();

  readonly tab = signal<'fints' | 'file'>('fints');
  readonly accounts = signal<AccountOption[]>([]);
  readonly accountId = signal<string>('');
  readonly lines = signal<StatementLine[]>([]);
  /** Pro Umsatz gewählte Kostenstelle (Vorschlag vorbelegt). */
  readonly chosenBudget = signal<Record<string, string>>({});

  readonly loadingLines = signal(false);
  readonly syncing = signal(false);
  readonly importing = signal(false);
  readonly confirmingId = signal<string>('');

  // --- FinTS-TAN-Schritt ---
  readonly sessionToken = signal<string>('');
  readonly challenge = signal<string>('');
  /** Optischer Challenge (photoTAN/QR-TAN) als Data-URL — leer = nur Text/Code (#fints-qrtan). */
  readonly challengeImage = signal<string>('');
  readonly decoupled = signal(false);
  readonly tanCode = signal('');
  readonly tanBusy = signal(false);

  private readonly costOptionsSig = signal<SelectOption[]>([]);
  readonly costCentreOptions = computed<SelectOption[]>(() => this.costOptionsSig());

  /** Konten für die FinTS-Lasche: nur sync-fähige (`fintsConfigured`). */
  readonly fintsAccountOptions = computed<SelectOption[]>(() =>
    this.accounts()
      .filter((a) => a.fintsConfigured)
      .map((a) => ({ value: a.id, label: a.name })),
  );
  /** Konten für die Datei-Lasche: alle aktiven. */
  readonly fileAccountOptions = computed<SelectOption[]>(() =>
    this.accounts().map((a) => ({ value: a.id, label: a.name })),
  );

  readonly hasPendingTan = computed(() => !!this.sessionToken());

  constructor() {
    // Beim Öffnen: Konten + Kostenstellen-Baum + offene Umsätze laden.
    effect(() => {
      if (this.open()) this.onOpen();
    });
  }

  private onOpen(): void {
    this.resetTan();
    this.api.listAccountOptions().subscribe({
      next: (accs) => {
        this.accounts.set(accs);
        if (!this.accountId() && accs.length) this.accountId.set(accs[0].id);
      },
      error: () => this.accounts.set([]),
    });
    this.api.tree().subscribe({
      next: (tree) => this.costOptionsSig.set(flattenBudgetOptions(tree)),
      error: () => this.costOptionsSig.set([]),
    });
    this.reloadLines();
  }

  reloadLines(): void {
    this.loadingLines.set(true);
    // Nur offene Umsätze (unmatched/suggested) — gebuchte/ignorierte ausblenden.
    this.api.listStatementLines({}).subscribe({
      next: (all) => {
        const open = all.filter((l) => l.matchState === 'unmatched' || l.matchState === 'suggested');
        this.lines.set(open);
        const chosen: Record<string, string> = {};
        for (const l of open) chosen[l.id] = l.suggestedBudgetId ?? '';
        this.chosenBudget.set(chosen);
        this.loadingLines.set(false);
      },
      error: () => {
        this.lines.set([]);
        this.loadingLines.set(false);
      },
    });
  }

  // ------------------------------------------------------------------ FinTS
  startSync(): void {
    const acc = this.accountId();
    if (!acc || this.syncing()) return;
    this.resetTan();
    this.syncing.set(true);
    this.api.fintsSync(acc as Uuid).subscribe({
      next: (res) => {
        this.syncing.set(false);
        this.handleSync(res);
      },
      error: (e) => {
        this.syncing.set(false);
        this.toast.error(this.syncError(e));
      },
    });
  }

  submitTan(): void {
    const acc = this.accountId();
    const token = this.sessionToken();
    if (!acc || !token || this.tanBusy()) return;
    this.tanBusy.set(true);
    this.api.fintsSubmitTan(acc as Uuid, token as Uuid, this.tanCode().trim()).subscribe({
      next: (res) => {
        this.tanBusy.set(false);
        if (res.status === 'needs_tan') {
          // decoupled: noch nicht freigegeben.
          this.toast.show(this.i18n.translate('fints.tanPending'), 'info');
          return;
        }
        this.resetTan();
        this.handleSync(res);
      },
      error: (e) => {
        this.tanBusy.set(false);
        this.toast.error(this.syncError(e));
      },
    });
  }

  private handleSync(res: BankSyncResult): void {
    if (res.status === 'needs_tan') {
      this.sessionToken.set(res.sessionToken ?? '');
      this.challenge.set(res.challenge ?? '');
      // Nur echte Bild-Data-URLs ins <img>-Binding lassen (Defense-in-Depth, #fints-review):
      // der Server liefert sie zwar geprüft, aber wir vertrauen dem String nicht blind.
      const img = res.challengeImage ?? '';
      this.challengeImage.set(/^data:image\/(png|jpe?g|gif|webp);base64,/i.test(img) ? img : '');
      this.decoupled.set(res.decoupled);
      return;
    }
    this.toast.success(
      this.i18n.translate('fints.imported', {
        imported: String(res.imported),
        duplicates: String(res.duplicates),
      }),
    );
    this.reloadLines();
  }

  private resetTan(): void {
    this.sessionToken.set('');
    this.challenge.set('');
    this.challengeImage.set('');
    this.decoupled.set(false);
    this.tanCode.set('');
  }

  private syncError(e: unknown): string {
    const code = (e as { error?: { code?: string } })?.error?.code;
    if (code === 'fints_not_configured') return this.i18n.translate('fints.errNotConfigured');
    if (code === 'fints_pin_undecryptable') return this.i18n.translate('fints.errPin');
    if (code === 'fints_tan_expired') return this.i18n.translate('fints.errTanExpired');
    return this.i18n.translate('fints.errSync');
  }

  // ------------------------------------------------------------------- file
  onFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    const acc = this.accountId();
    if (!file || !acc) return;
    this.importing.set(true);
    this.api.importStatementFile(acc as Uuid, file).subscribe({
      next: (res) => {
        this.importing.set(false);
        input.value = '';
        this.toast.success(
          this.i18n.translate('fints.imported', {
            imported: String(res.imported),
            duplicates: String(res.duplicates),
          }),
        );
        this.reloadLines();
      },
      error: () => {
        this.importing.set(false);
        input.value = '';
        this.toast.error(this.i18n.translate('fints.errFile'));
      },
    });
  }

  // -------------------------------------------------------------- reconcile
  setChosen(lineId: string, budgetId: string): void {
    this.chosenBudget.update((m) => ({ ...m, [lineId]: budgetId }));
  }

  confirm(line: StatementLine): void {
    const budgetId = this.chosenBudget()[line.id];
    if (!budgetId || this.confirmingId()) return;
    this.confirmingId.set(line.id);
    this.api.confirmStatementLine(line.id, { budgetId: budgetId as Uuid }).subscribe({
      next: () => {
        this.confirmingId.set('');
        this.lines.update((ls) => ls.filter((l) => l.id !== line.id));
        this.toast.success(this.i18n.translate('fints.booked'));
        this.changed.emit();
      },
      error: () => {
        this.confirmingId.set('');
        this.toast.error(this.i18n.translate('fints.errBook'));
      },
    });
  }

  ignore(line: StatementLine): void {
    if (this.confirmingId()) return;
    this.confirmingId.set(line.id);
    this.api.ignoreStatementLine(line.id).subscribe({
      next: () => {
        this.confirmingId.set('');
        this.lines.update((ls) => ls.filter((l) => l.id !== line.id));
        this.changed.emit();
      },
      error: () => {
        this.confirmingId.set('');
        this.toast.error(this.i18n.translate('fints.errBook'));
      },
    });
  }

  money(amount: string): string {
    const n = Math.abs(Number(amount));
    return n.toLocaleString(this.i18n.locale() === 'en' ? 'en-US' : 'de-DE', {
      style: 'currency',
      currency: 'EUR',
    });
  }

  close(): void {
    // Einmal-TAN + Challenge nicht über das Schließen hinaus im (dauerhaft gemounteten)
    // Component-State liegen lassen (#fints-review).
    this.resetTan();
    this.closed.emit();
  }
}
