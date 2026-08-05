import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { type IconName, IconComponent } from '@stupa-makers/ui-kit';

interface AdminTile {
  link: string;
  title: TranslationKey;
  desc: TranslationKey;
  icon: IconName;
  /** Visible if the user holds at least ONE of these permissions (ANY-of). It mirrors
   *  the route-guard right in `app.routes.ts`. This is UX only. The backend stays
   *  authoritative. */
  permissions: string[];
}

/**
 * Admin landing. Entry into the config UIs. Each tile is its own (lazy) route with
 * an icon-left layout and a one-line description.
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

  protected readonly tiles: AdminTile[] = [
    { link: 'users', title: 'admin.home.users', desc: 'admin.home.usersDesc', icon: 'members', permissions: ['admin.users'] },
    { link: 'roles', title: 'admin.home.roles', desc: 'admin.home.rolesDesc', icon: 'roles', permissions: ['admin.roles'] },
    { link: 'group-mappings', title: 'admin.home.groupMappings', desc: 'admin.home.groupMappingsDesc', icon: 'key', permissions: ['admin.group_mappings'] },
    { link: 'gremien', title: 'admin.home.gremien', desc: 'admin.home.gremienDesc', icon: 'parliament', permissions: ['admin.gremien'] },
    { link: 'budget-pots', title: 'budget.tree.title', desc: 'admin.home.budgetPotsDesc', icon: 'euro', permissions: ['budget.structure'] },
    { link: 'forms', title: 'admin.home.formBuilder', desc: 'admin.home.formBuilderDesc', icon: 'form', permissions: ['form.configure'] },
    { link: 'flow', title: 'admin.home.flowEditor', desc: 'admin.home.flowEditorDesc', icon: 'flow', permissions: ['flow.configure'] },
    { link: 'branding', title: 'admin.home.branding', desc: 'admin.home.brandingDesc', icon: 'palette', permissions: ['admin.site'] },
    { link: 'webhooks', title: 'admin.home.webhooks', desc: 'admin.home.webhooksDesc', icon: 'webhook', permissions: ['webhook.manage'] },
    { link: 'delegations', title: 'admin.home.delegations', desc: 'admin.home.delegationsDesc', icon: 'repeat', permissions: ['admin.delegations'] },
    { link: 'audit', title: 'admin.audit.title', desc: 'admin.audit.desc', icon: 'audit', permissions: ['audit.read'] },
    { link: 'deadlines', title: 'admin.deadlines.title', desc: 'admin.deadlines.subtitle', icon: 'clock', permissions: ['admin.deadlines'] },
    { link: 'privacy', title: 'admin.home.privacy', desc: 'admin.home.privacyDesc', icon: 'key', permissions: ['privacy.manage'] },
    { link: 'notifications', title: 'admin.notifications.title', desc: 'admin.notifications.intro', icon: 'bell', permissions: ['admin.notifications'] },
    { link: 'mail-templates', title: 'admin.home.mailTemplates', desc: 'admin.home.mailTemplatesDesc', icon: 'send', permissions: ['admin.notifications'] },
  ];

  /** Only tiles the user has the right for. Admin sees everything (auth.can). */
  protected readonly visibleTiles = computed(() =>
    this.tiles.filter((t) => this.auth.canAny(...t.permissions)),
  );
}
