import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { type IconName, IconComponent } from '@shared/ui';

interface AdminTile {
  link: string;
  title: TranslationKey;
  desc: TranslationKey;
  icon: IconName;
  /** Sichtbar, wenn der Nutzer mindestens EINE dieser Permissions hat (ANY-of) —
   *  spiegelt das Route-Guard-Recht (#5-1). Nur UX; das Backend bleibt autoritativ. */
  permissions: string[];
}

/**
 * Admin-Landing (T-34). Einstieg in die Config-UIs. Jede Kachel ist eine eigene
 * (lazy) Route mit Icon-links-Layout und einzeiliger Beschreibung.
 */
@Component({
  selector: 'app-admin-home',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, IconComponent],
  templateUrl: './admin-home.component.html',
  styleUrl: './admin-home.component.scss',
})
export class AdminHomeComponent {
  private readonly auth = inject(AuthService);

  // Permissions je Kachel = Route-Guard-Recht aus app.routes.ts. ANY-of, damit
  // mehrfach-gegatete Routen (falls künftig) korrekt greifen.
  protected readonly tiles: AdminTile[] = [
    { link: 'users', title: 'admin.home.users', desc: 'admin.home.usersDesc', icon: 'members', permissions: ['admin.users'] },
    { link: 'roles', title: 'admin.home.roles', desc: 'admin.home.rolesDesc', icon: 'roles', permissions: ['admin.roles'] },
    { link: 'group-mappings', title: 'admin.home.groupMappings', desc: 'admin.home.groupMappingsDesc', icon: 'key', permissions: ['admin.group_mappings'] },
    { link: 'gremien', title: 'admin.home.gremien', desc: 'admin.home.gremienDesc', icon: 'parliament', permissions: ['admin.gremien'] },
    { link: 'budget-pots', title: 'budget.tree.title', desc: 'admin.home.budgetPotsDesc', icon: 'euro', permissions: ['budget.structure'] },
    { link: 'accounts', title: 'admin.accounts.title', desc: 'admin.accounts.desc', icon: 'building', permissions: ['account.manage'] },
    { link: 'forms', title: 'admin.home.formBuilder', desc: 'admin.home.formBuilderDesc', icon: 'form', permissions: ['form.configure'] },
    { link: 'flow', title: 'admin.home.flowEditor', desc: 'admin.home.flowEditorDesc', icon: 'flow', permissions: ['flow.configure'] },
    { link: 'branding', title: 'admin.home.branding', desc: 'admin.home.brandingDesc', icon: 'palette', permissions: ['admin.site'] },
    { link: 'webhooks', title: 'admin.home.webhooks', desc: 'admin.home.webhooksDesc', icon: 'webhook', permissions: ['webhook.manage'] },
    { link: 'delegations', title: 'admin.home.delegations', desc: 'admin.home.delegationsDesc', icon: 'repeat', permissions: ['admin.delegations'] },
    { link: 'audit', title: 'admin.audit.title', desc: 'admin.audit.desc', icon: 'audit', permissions: ['audit.read'] },
    { link: 'deadlines', title: 'admin.deadlines.title', desc: 'admin.deadlines.subtitle', icon: 'clock', permissions: ['admin.deadlines'] },
    { link: 'notifications', title: 'admin.notifications.title', desc: 'admin.notifications.intro', icon: 'bell', permissions: ['admin.notifications'] },
    { link: 'mail-templates', title: 'admin.home.mailTemplates', desc: 'admin.home.mailTemplatesDesc', icon: 'send', permissions: ['admin.notifications'] },
  ];

  /** Nur Kacheln, deren Recht der Nutzer hat (#5-1). Admin sieht alles (auth.can). */
  protected readonly visibleTiles = computed(() =>
    this.tiles.filter((t) => this.auth.canAny(...t.permissions)),
  );
}
