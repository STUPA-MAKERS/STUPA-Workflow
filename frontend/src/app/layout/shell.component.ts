import { UpperCasePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { ThemeService } from '@core/theme/theme.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Locale } from '@core/i18n/translations';
import { ToastComponent } from '@shared/ui/toast/toast.component';

interface NavItem {
  path: string;
  labelKey: Parameters<TranslatePipe['transform']>[0];
}

/** App-Rahmen: Header (Logo/Nav/Theme/Sprache), Inhalt, Footer, Toasts. */
@Component({
  selector: 'app-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    TranslatePipe,
    UpperCasePipe,
    ToastComponent,
  ],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss',
})
export class ShellComponent {
  readonly theme = inject(ThemeService);
  readonly i18n = inject(I18nService);

  readonly nav: NavItem[] = [
    { path: '/dashboard', labelKey: 'nav.dashboard' },
    { path: '/applications', labelKey: 'nav.applications' },
    { path: '/voting', labelKey: 'nav.voting' },
    { path: '/meetings', labelKey: 'nav.meetings' },
    { path: '/budget', labelKey: 'nav.budget' },
    { path: '/admin', labelKey: 'nav.admin' },
  ];

  toggleTheme(): void {
    this.theme.toggle();
  }

  setLocale(value: string): void {
    this.i18n.setLocale(value as Locale);
  }
}
