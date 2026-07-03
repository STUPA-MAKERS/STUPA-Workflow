import { computed, inject, signal, type ElementRef } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService } from '@stupa-makers/ui-kit';
import type { Uuid } from '@core/api/models';
import {
  type BankSyncResult,
  BudgetTreeApi,
  type FintsCredentialStatus,
} from '../budget/budget-tree.api';
import { problemCode } from '../budget/expense-display.util';
import { fintsErrorKey, safeChallengeImage } from './konten.util';
import type { KontenLinesState } from './konten-lines.state';

/**
 * Per-booker FinTS credential (connect dialog) + sync / TAN (PSD2 SCA) flow
 * incl. the 6-box OTP input. Write access is enforced server-side.
 */
export class FintsSyncState {
  private readonly api = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  // --- credential / connect dialog ---
  readonly credStatus = signal<FintsCredentialStatus | null>(null);
  readonly connectOpen = signal(false);
  readonly credLogin = signal('');
  readonly credPin = signal('');
  readonly savingCred = signal(false);
  readonly configured = computed(() => !!this.credStatus()?.configured);
  readonly connected = computed(() => !!this.credStatus()?.hasCredential);
  readonly locked = computed(() => {
    const until = this.credStatus()?.fintsLockedUntil;
    return !!until && new Date(until).getTime() > Date.now();
  });
  readonly lockedUntilLabel = computed(() => {
    const until = this.credStatus()?.fintsLockedUntil;
    return until ? new Date(until).toLocaleString() : '';
  });

  // --- sync / TAN ---
  readonly syncing = signal(false);
  readonly sessionToken = signal<string>('');
  readonly challenge = signal<string>('');
  readonly challengeImage = signal<string>('');
  readonly decoupled = signal(false);
  readonly tanCode = signal('');
  readonly tanBusy = signal(false);
  readonly hasPendingTan = computed(() => !!this.sessionToken());

  // --- OTP (6 boxes) ---
  readonly otpLength = 6;
  readonly otpSlots = Array.from({ length: 6 }, (_, i) => i);
  readonly otpDigits = signal<string[]>(Array.from({ length: 6 }, () => ''));
  readonly otpMode = signal(true);
  readonly tanReady = computed(() => {
    const t = this.tanCode().trim();
    return this.otpMode() ? t.length === this.otpLength : t.length > 0;
  });

  constructor(
    private readonly lines: KontenLinesState,
    private readonly host: ElementRef<HTMLElement>,
  ) {}

  loadCredStatus(accountId: string): void {
    this.api.fintsCredentialStatus(accountId as Uuid).subscribe({
      next: (s) => {
        this.credStatus.set(s);
        this.credLogin.set(s.fintsLogin ?? '');
        this.credPin.set('');
      },
      error: () => this.credStatus.set(null),
    });
  }

  openConnect(): void {
    this.credLogin.set(this.credStatus()?.fintsLogin ?? '');
    this.credPin.set('');
    this.connectOpen.set(true);
  }

  closeConnect(): void {
    this.connectOpen.set(false);
    this.credPin.set('');
  }

  saveCred(): void {
    const acc = this.lines.accountId();
    const login = this.credLogin().trim();
    const pin = this.credPin();
    if (!acc || !login || !pin || this.savingCred()) return;
    this.savingCred.set(true);
    this.api.setFintsCredential(acc as Uuid, { fintsLogin: login, fintsPin: pin }).subscribe({
      next: (s) => {
        this.savingCred.set(false);
        this.credStatus.set(s);
        this.closeConnect();
        this.toast.success(this.i18n.translate('fints.credSaved'));
      },
      error: (e) => {
        this.savingCred.set(false);
        this.toast.error(this.syncError(e));
      },
    });
  }

  removeCred(): void {
    const acc = this.lines.accountId();
    if (!acc || this.savingCred()) return;
    this.savingCred.set(true);
    this.api.deleteFintsCredential(acc as Uuid).subscribe({
      next: () => {
        this.savingCred.set(false);
        this.resetTan();
        this.closeConnect();
        this.loadCredStatus(acc);
        this.toast.success(this.i18n.translate('fints.credRemoved'));
      },
      error: () => {
        this.savingCred.set(false);
        this.toast.error(this.i18n.translate('fints.errBook'));
      },
    });
  }

  startSync(): void {
    const acc = this.lines.accountId();
    if (!acc || this.syncing() || this.locked()) return;
    if (!this.connected()) {
      // No credential yet → open the connect dialog instead of failing.
      this.openConnect();
      return;
    }
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
        this.refreshOnLock(e);
      },
    });
  }

  submitTan(): void {
    const acc = this.lines.accountId();
    const token = this.sessionToken();
    if (!acc || !token || this.tanBusy()) return;
    this.tanBusy.set(true);
    this.api.fintsSubmitTan(acc as Uuid, token as Uuid, this.tanCode().trim()).subscribe({
      next: (res) => {
        this.tanBusy.set(false);
        if (res.status === 'needs_tan') {
          this.toast.show(this.i18n.translate('fints.tanPending'), 'info');
          return;
        }
        this.resetTan();
        this.handleSync(res);
      },
      error: (e) => {
        this.tanBusy.set(false);
        this.toast.error(this.syncError(e));
        this.refreshOnLock(e);
      },
    });
  }

  private handleSync(res: BankSyncResult): void {
    if (res.status === 'needs_tan') {
      this.sessionToken.set(res.sessionToken ?? '');
      this.challenge.set(res.challenge ?? '');
      this.challengeImage.set(safeChallengeImage(res.challengeImage ?? ''));
      this.decoupled.set(res.decoupled);
      return;
    }
    this.toast.success(
      this.i18n.translate('fints.imported', {
        imported: String(res.imported),
        duplicates: String(res.duplicates),
      }),
    );
    this.lines.reloadLines();
    this.loadCredStatus(this.lines.accountId());
    this.lines.refreshAccounts();
  }

  /** Bank lock / auth rejection changes the lock state → reload the status. */
  refreshOnLock(e: unknown): void {
    const code = problemCode(e);
    const acc = this.lines.accountId();
    if (acc && (code === 'fints_bank_locked' || code === 'fints_auth_rejected')) {
      this.loadCredStatus(acc);
    }
  }

  syncError(e: unknown): string {
    return this.i18n.translate(fintsErrorKey(e));
  }

  resetTan(): void {
    this.sessionToken.set('');
    this.challenge.set('');
    this.challengeImage.set('');
    this.decoupled.set(false);
    this.tanCode.set('');
    this.resetOtp();
    this.otpMode.set(true);
  }

  /** Cancel the TAN dialog — discards the pending session. */
  closeTan(): void {
    this.resetTan();
  }

  // --- OTP handlers ---
  onOtpInput(i: number, ev: Event): void {
    const el = ev.target as HTMLInputElement;
    const digit = el.value.replace(/\D/g, '').slice(-1);
    this.otpDigits.update((d) => {
      const n = [...d];
      n[i] = digit;
      return n;
    });
    el.value = digit;
    this.syncTanFromDigits();
    if (digit && i < this.otpLength - 1) this.focusOtp(i + 1);
  }

  onOtpKeydown(i: number, ev: KeyboardEvent): void {
    if (ev.key === 'Backspace' && !this.otpDigits()[i] && i > 0) {
      ev.preventDefault();
      this.otpDigits.update((d) => {
        const n = [...d];
        n[i - 1] = '';
        return n;
      });
      this.syncTanFromDigits();
      this.focusOtp(i - 1);
    }
  }

  onOtpPaste(ev: ClipboardEvent): void {
    const digits = (ev.clipboardData?.getData('text') ?? '').replace(/\D/g, '');
    if (!digits) return;
    ev.preventDefault();
    const chars = digits.slice(0, this.otpLength).split('');
    this.otpDigits.set(Array.from({ length: this.otpLength }, (_, k) => chars[k] ?? ''));
    this.syncTanFromDigits();
    this.focusOtp(Math.min(chars.length, this.otpLength) - 1);
  }

  useSingleTanField(): void {
    this.otpMode.set(false);
    this.tanCode.set('');
    this.resetOtp();
  }

  private syncTanFromDigits(): void {
    this.tanCode.set(this.otpDigits().join(''));
  }

  private resetOtp(): void {
    this.otpDigits.set(Array.from({ length: this.otpLength }, () => ''));
  }

  private focusOtp(i: number): void {
    this.host.nativeElement.querySelector<HTMLInputElement>(`[data-otp="${i}"]`)?.focus();
  }
}
