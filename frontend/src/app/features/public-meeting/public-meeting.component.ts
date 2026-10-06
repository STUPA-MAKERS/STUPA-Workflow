import {
  ChangeDetectionStrategy,
  Component,
  type OnDestroy,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { ThemeService } from '@core/theme/theme.service';
import { LanguageSelectComponent } from '../../layout/language-select/language-select.component';
import { SiteFooterComponent } from '../../layout/site-footer/site-footer.component';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { AvatarComponent } from '@shared/ui/avatar/avatar.component';
import { NoteComponent } from '@shared/ui/note/note.component';
import { RowMenuComponent, type RowMenuSection } from '@shared/ui/row-menu/row-menu.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { meetingStatus } from '@shared/status-kind.util';
import { ButtonComponent, IconComponent, InputComponent } from '@stupa-makers/ui-kit';
import { clockTime } from '../meetings/meetings-display.util';
import { GuestSessionService } from './guest-session.service';
import { GuestViewComponent } from './guest-view.component';

/** The join code: six characters without the easily confused ones (0, O, 1, I, L). */
const CODE_RE = /^[A-HJ-NP-Z2-9]{6}$/;

/** Normalize a typed code: "7kq-4mp" → "7KQ4MP". */
export function normalizeJoinCode(raw: string): string {
  return raw.toUpperCase().replace(/[^A-Z0-9]/g, '');
}

/**
 * The public join page of a meeting, `/j/:code` (#17, boards Telefon-Beitreten): the
 * QR code of the beamer leads here. One page with every state of the request: the name
 * form, "Warte auf Freigabe", "Anfrage abgelehnt" (a new request after three minutes),
 * "nicht mehr öffentlich", "beendet" and, after the admission, the participant view.
 *
 * No account and no app navigation: the public frame with its footer. A member logs in
 * instead ("Mitglied? Mit Konto anmelden"); there is no duplicate check of names. The
 * page updates itself over the guest channel; a reload gives the same state (cookie).
 */
@Component({
  selector: 'app-public-meeting',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [GuestSessionService],
  imports: [
    NgTemplateOutlet,
    FormsModule,
    TranslatePipe,
    AvatarComponent,
    ButtonComponent,
    IconComponent,
    InputComponent,
    NoteComponent,
    RowMenuComponent,
    StatusTextComponent,
    GuestViewComponent,
    SiteFooterComponent,
    LanguageSelectComponent,
  ],
  templateUrl: './public-meeting.component.html',
  styleUrl: './public-meeting.component.scss',
})
export class PublicMeetingComponent implements OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  protected readonly guest = inject(GuestSessionService);
  private readonly theme = inject(ThemeService);
  /** The wordmark of the own header, in the colours of the theme. */
  protected readonly logoSrc = computed(() => `assets/logos/stupa-wordmark-${this.theme.resolved()}.svg`);

  protected readonly name = signal('');
  /** The pending request shows the rename form. */
  protected readonly renaming = signal(false);
  protected readonly typedCode = signal('');
  /** A tick per second while a rejected guest waits for the next request. */
  protected readonly now = signal(Date.now());
  private ticker: ReturnType<typeof setInterval> | null = null;

  protected readonly state = this.guest.state;
  protected readonly head = computed(() => this.guest.me()?.meeting ?? this.guest.head());
  protected readonly status = computed(() => {
    const h = this.head();
    return h ? meetingStatus(h.status) : null;
  });
  /** "Fachschaft Informatik · seit 18:15". */
  protected readonly metaLine = computed(() => {
    const h = this.head();
    if (!h) return '';
    const parts: string[] = [];
    if (h.gremiumName) parts.push(h.gremiumName);
    if (h.status === 'live' && h.startedAt) {
      parts.push(this.i18n.translate('guests.page.since', { time: clockTime(h.startedAt, this.i18n.locale()) }));
    } else if (h.date) {
      parts.push(this.dateText(h.date, h.startTime));
    }
    return parts.join(' · ');
  });
  /** The own name, or "Gast n". */
  protected readonly ownName = computed(() => {
    const me = this.guest.me();
    if (!me) return '';
    return me.displayName ?? this.i18n.translate('guests.pseudonym', { n: me.number });
  });
  protected readonly menu = computed<RowMenuSection[]>(() => {
    const st = this.state();
    if (st === 'admitted') {
      return [{ items: [{ id: 'leave', label: this.i18n.translate('guests.page.leave'), icon: 'logout', danger: true }] }];
    }
    if (st === 'pending') {
      return [
        {
          items: [
            { id: 'rename', label: this.i18n.translate('guests.page.rename'), icon: 'edit' },
            { id: 'leave', label: this.i18n.translate('guests.page.withdraw'), icon: 'x', danger: true },
          ],
        },
      ];
    }
    return [];
  });
  /** The intro line of the form: vote or watch. */
  protected readonly introKey = computed<TranslationKey>(() =>
    this.head()?.guestsMode === 'watch' ? 'guests.join.introWatch' : 'guests.join.introVote',
  );
  /** Seconds until a rejected or removed guest may ask again. */
  protected readonly waitSeconds = computed(() => {
    const me = this.guest.me();
    if (!me?.retryAfter) return 0;
    const left = me.retryAfter * 1000 - (this.now() - this.guest.fetchedAt());
    return Math.max(0, Math.ceil(left / 1000));
  });
  /** "Wieder möglich ab 18:55 (3 Minuten)". */
  protected readonly retryLine = computed(() => {
    const me = this.guest.me();
    if (!me?.retryAfter) return '';
    const at = new Date(this.guest.fetchedAt() + me.retryAfter * 1000).toISOString();
    return this.i18n.translate('guests.page.retryAt', {
      time: clockTime(at, this.i18n.locale()),
      n: Math.max(1, Math.ceil(this.waitSeconds() / 60)),
    });
  });
  protected readonly joinErrorKey = computed<TranslationKey | null>(() => {
    const code = this.guest.joinError();
    if (!code) return null;
    if (code === 'altcha_failed') return 'guests.join.errorAltcha';
    if (code === 'rate_limited') return 'guests.join.errorRate';
    return 'guests.join.error';
  });
  protected readonly nameValid = computed(() => {
    const n = this.name().trim();
    return n.length >= 2 && n.length <= 80;
  });

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      const code = normalizeJoinCode(pm.get('code') ?? '');
      this.renaming.set(false);
      this.guest.load(code);
    });
    // The countdown of a rejected or removed guest runs only while it matters.
    effect(() => {
      const st = this.state();
      untracked(() => {
        if (st === 'rejected' || st === 'removed') this.startTicker();
        else this.stopTicker();
      });
    });
    // The rename form starts with the current name.
    effect(() => {
      const me = this.guest.me();
      untracked(() => {
        if (me?.displayName && !this.name()) this.name.set(me.displayName);
      });
    });
  }

  join(): void {
    if (!this.nameValid()) return;
    void this.guest.join(this.name());
  }

  /** "Erneut anfragen" with the name of the refused request. */
  retry(): void {
    const name = this.guest.me()?.displayName ?? this.name();
    void this.guest.join(name);
  }

  saveRename(): void {
    if (!this.nameValid()) return;
    this.guest.rename(this.name());
    this.renaming.set(false);
  }

  onMenu(id: string): void {
    if (id === 'rename') this.renaming.set(true);
    else if (id === 'leave') this.guest.leave();
  }

  /** "Mitglied? Mit Konto anmelden". */
  login(): void {
    this.auth.login();
  }

  /** A typed code on the page of an unknown code. */
  goToCode(): void {
    const code = normalizeJoinCode(this.typedCode());
    if (CODE_RE.test(code)) void this.router.navigate(['/j', code]);
  }

  private startTicker(): void {
    if (this.ticker !== null) return;
    this.now.set(Date.now());
    this.ticker = setInterval(() => this.now.set(Date.now()), 1000);
  }

  private stopTicker(): void {
    if (this.ticker !== null) clearInterval(this.ticker);
    this.ticker = null;
  }

  private dateText(isoDate: string, time: string | null): string {
    const d = new Date(`${isoDate}T${time ? time.slice(0, 5) : '00:00'}:00`);
    if (Number.isNaN(d.getTime())) return isoDate;
    return new Intl.DateTimeFormat(this.i18n.formatLocale(), {
      weekday: 'short',
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      ...(time ? { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' as const } : {}),
    }).format(d);
  }

  ngOnDestroy(): void {
    this.stopTicker();
  }
}
