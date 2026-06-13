import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Subject, debounceTime, distinctUntilChanged, switchMap } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  type Delegation,
  type DelegationRecipient,
  DelegationsApiService,
  type MeetingDelegationContext,
} from '@core/api/delegations.service';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import {
  BadgeComponent,
  ButtonComponent,
  CardComponent,
  CheckboxComponent,
  DialogComponent,
  SelectComponent,
  type SelectOption,
} from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';

/**
 * »Vertretung« einer Sitzung (#delegation-rework): Karte auf der Sitzungsseite.
 *
 * Zeigt die eigene ausgehende Vertretung (inkl. Widerruf bis Sitzungsbeginn) und
 * an mich gerichtete Delegationen; der »Vertretung einrichten«-Dialog wählt den
 * Empfänger aus Gremium-Mitgliedern + Stellvertreter-Pool (Dropdown; bei
 * freigeschalteten Externen zusätzlich serverseitige Namenssuche). Stimmrecht
 * mit übertragen nur, wenn der Betreiber es global freigeschaltet hat. Alle
 * Regeln (Deadline, Empfänger-Kreis, Ketten) erzwingt der Server — die Karte
 * blendet nur offensichtlich Unzulässiges aus.
 */
@Component({
  selector: 'app-meeting-delegation-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    CheckboxComponent,
    DialogComponent,
    SelectComponent,
  ],
  templateUrl: './meeting-delegation-card.component.html',
  styleUrl: './meeting-delegation-card.component.scss',
})
export class MeetingDelegationCardComponent {
  private readonly api = inject(DelegationsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  /** Sitzung, auf die sich die Vertretung bezieht. */
  readonly meetingId = input.required<Uuid>();

  protected readonly ctx = signal<MeetingDelegationContext | null>(null);
  protected readonly dialogOpen = signal(false);
  protected readonly busy = signal(false);
  protected readonly delegateId = signal<Uuid | ''>('');
  protected readonly delegateVoting = signal(false);
  protected readonly query = signal('');
  /** Suchergebnisse der serverseitigen Namenssuche (nur bei Externen-Flag). */
  protected readonly searched = signal<DelegationRecipient[] | null>(null);
  private readonly query$ = new Subject<string>();

  /** Karte zeigen, sobald Delegation im Gremium aktiv und für mich relevant ist. */
  protected readonly visible = computed(() => {
    const c = this.ctx();
    if (!c || !c.allowVoteDelegation) return false;
    return c.canDelegate || c.myDelegation !== null || c.incoming.length > 0;
  });

  /** Einrichten möglich: berechtigt + Sitzung geplant + (Pool- oder normale) Frist offen.
   *  Pool-Empfänger gehen bis Sitzungsbeginn — daher blockt nur `meetingStarted` hart. */
  protected readonly canCreate = computed(() => {
    const c = this.ctx();
    return Boolean(c && c.canDelegate && !c.meetingStarted && this.hasOpenWindow(c));
  });

  protected readonly recipientOptions = computed<SelectOption[]>(() => {
    const c = this.ctx();
    const list = this.searched() ?? c?.recipients ?? [];
    const pool = this.i18n.translate('delegation.dialog.poolSuffix');
    return list.map((r) => ({
      value: r.principalId,
      label: (r.displayName || r.principalId) + (r.viaPool ? ` ${pool}` : ''),
    }));
  });

  protected readonly selectedRecipient = computed<DelegationRecipient | null>(() => {
    const id = this.delegateId();
    const list = this.searched() ?? this.ctx()?.recipients ?? [];
    return list.find((r) => r.principalId === id) ?? null;
  });

  constructor() {
    effect(() => {
      const id = this.meetingId();
      this.ctx.set(null);
      this.api.meetingContext(id).subscribe({
        next: (c) => this.ctx.set(c),
        error: () => this.ctx.set(null),
      });
    });
    this.query$
      .pipe(
        debounceTime(250),
        distinctUntilChanged(),
        switchMap((q) => this.api.recipients(this.meetingId(), q)),
        takeUntilDestroyed(),
      )
      .subscribe((list) => this.searched.set(list));
  }

  /** Nach Deadline sind nur noch Pool-Empfänger zulässig — Fenster gilt als offen,
   *  solange es mindestens einen wählbaren Empfänger gibt. */
  private hasOpenWindow(c: MeetingDelegationContext): boolean {
    if (!c.deadlinePassed) return true;
    return c.recipients.some((r) => r.viaPool);
  }

  protected openDialog(): void {
    this.delegateId.set('');
    this.delegateVoting.set(false);
    this.query.set('');
    this.searched.set(null);
    this.dialogOpen.set(true);
  }

  protected search(q: string): void {
    this.query.set(q);
    this.query$.next(q);
  }

  protected create(): void {
    const id = this.delegateId();
    if (!id || this.busy()) return;
    this.busy.set(true);
    this.api
      .create({ meetingId: this.meetingId(), delegateId: id, delegateVoting: this.delegateVoting() })
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.dialogOpen.set(false);
          this.toast.success(this.i18n.translate('delegation.toast.created'));
          this.reload();
        },
        error: (err: { error?: { detail?: string } }) => {
          this.busy.set(false);
          this.toast.error(err.error?.detail ?? this.i18n.translate('delegation.toast.createFailed'));
        },
      });
  }

  protected revoke(d: Delegation): void {
    if (this.busy()) return;
    this.busy.set(true);
    this.api.revoke(d.id).subscribe({
      next: () => {
        this.busy.set(false);
        this.toast.success(this.i18n.translate('delegation.toast.revoked'));
        this.reload();
      },
      error: () => {
        this.busy.set(false);
        this.toast.error(this.i18n.translate('delegation.toast.revokeFailed'));
      },
    });
  }

  private reload(): void {
    this.api.meetingContext(this.meetingId()).subscribe({
      next: (c) => this.ctx.set(c),
      error: () => {},
    });
  }
}
