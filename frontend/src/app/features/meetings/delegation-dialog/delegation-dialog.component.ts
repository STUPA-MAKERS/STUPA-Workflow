import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Subject, debounceTime, distinctUntilChanged, of, switchMap } from 'rxjs';
import { catchError } from 'rxjs/operators';
import {
  type Delegation,
  type DelegationRecipient,
  DelegationsApiService,
  type MeetingDelegationContext,
} from '@core/api/delegations.service';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { AvatarComponent } from '@shared/ui/avatar/avatar.component';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  SwitchComponent,
  ToastService,
} from '@stupa-makers/ui-kit';

/**
 * "Vertretung einrichten" (board Teilnahme-Vertretung): the member picks who represents
 * them in one meeting.
 *
 * - "Deine Stellvertretung": the substitutes of the member (the pool of the gremium,
 *   `viaPool`). They can take over without a lead time until the meeting starts.
 * - "Andere Mitglieder": the other members of the gremium, with a search. They need the
 *   lead time of the gremium: after the deadline the rows are off. When the gremium
 *   allows external substitutes, the search also asks the server for other persons.
 * - "Stimmrecht mit übertragen" with the line that says what it means.
 *
 * The server checks every rule again (deadline, recipients, no chains). The dialog
 * reports the new delegation through `created`.
 */
@Component({
  selector: 'app-delegation-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    NgTemplateOutlet,
    TranslatePipe,
    LocalizedDatePipe,
    AvatarComponent,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    SwitchComponent,
  ],
  templateUrl: './delegation-dialog.component.html',
  styleUrl: './delegation-dialog.component.scss',
})
export class DelegationDialogComponent {
  private readonly api = inject(DelegationsApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = input.required<boolean>();
  readonly context = input.required<MeetingDelegationContext>();
  /** "35. Sitzung des Studierendenparlaments · Di, 13.10.2026". */
  readonly subtitle = input('');

  readonly closed = output<void>();
  readonly created = output<Delegation>();

  protected readonly selected = signal<Uuid | ''>('');
  protected readonly voting = signal(false);
  protected readonly query = signal('');
  protected readonly busy = signal(false);
  /** The hits of the server search (externals allowed only), or `null`. */
  private readonly searched = signal<DelegationRecipient[] | null>(null);
  private readonly query$ = new Subject<string>();

  /** The substitutes of the member: no lead time until the start. */
  protected readonly substitutes = computed(() => this.context().recipients.filter((r) => r.viaPool));

  /** The other members (and, with a server search, external persons). */
  protected readonly others = computed(() => {
    const searched = this.searched();
    const base = searched ?? this.context().recipients;
    const needle = this.query().trim().toLowerCase();
    return base.filter(
      (r) =>
        !r.viaPool && (searched !== null || !needle || (r.displayName ?? '').toLowerCase().includes(needle)),
    );
  });

  /** Other members only until the deadline of the gremium. */
  protected readonly othersOpen = computed(() => !this.context().deadlinePassed);

  protected readonly canSubmit = computed(() => this.selected() !== '' && !this.busy());

  constructor() {
    // A new opening starts empty.
    effect(() => {
      if (!this.open()) return;
      untracked(() => {
        this.selected.set('');
        this.voting.set(false);
        this.query.set('');
        this.searched.set(null);
      });
    });
    this.query$
      .pipe(
        debounceTime(250),
        distinctUntilChanged(),
        switchMap((q) =>
          q.trim()
            ? this.api.recipients(this.context().meetingId, q).pipe(catchError(() => of(null)))
            : of(null),
        ),
        takeUntilDestroyed(),
      )
      .subscribe((list) => this.searched.set(list));
  }

  /** The second line of a person: "Stellvertretung", "Mitglied" or "Extern". */
  protected roleKey(r: DelegationRecipient): TranslationKey {
    if (r.viaPool) return 'participant.delegation.substitute';
    return r.isMember ? 'participant.delegation.member' : 'participant.delegation.external';
  }

  protected name(r: DelegationRecipient): string {
    return r.displayName || this.i18n.translate('participant.delegation.unnamed');
  }

  protected search(q: string): void {
    this.query.set(q);
    // Without external substitutes the list of members is complete: filter it here.
    if (this.context().delegationAllowExternal) this.query$.next(q);
  }

  protected pick(r: DelegationRecipient): void {
    if (!r.viaPool && !this.othersOpen()) return;
    this.selected.set(r.principalId);
  }

  protected submit(): void {
    if (!this.canSubmit()) return;
    const delegateId = this.selected();
    this.busy.set(true);
    const c = this.context();
    this.api
      .create({
        meetingId: c.meetingId,
        delegateId,
        delegateVoting: c.votingDelegationEnabled && this.voting(),
      })
      .subscribe({
        next: (d) => {
          this.busy.set(false);
          this.toast.success(this.i18n.translate('delegation.toast.created'));
          this.created.emit(d);
        },
        error: (err: { error?: { detail?: string } }) => {
          this.busy.set(false);
          this.toast.error(err.error?.detail ?? this.i18n.translate('delegation.toast.createFailed'));
        },
      });
  }
}
