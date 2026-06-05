import type { Routes } from '@angular/router';
import { authGuard } from '@core/auth/auth.guard';
import { ShellComponent } from './layout/shell.component';

/**
 * Routing-Gerüst (T-03). OIDC-Bereiche sind per `authGuard` geschützt; einzelne
 * Bereiche fordern zusätzlich eine RBAC-Permission (`data.permission`, T-36).
 * Feature-Inhalte folgen je Strang (T-30…T-35); offene Bereiche zeigen vorerst
 * den Platzhalter, sind aber bereits korrekt gated.
 */
export const routes: Routes = [
  {
    path: '',
    component: ShellComponent,
    children: [
      {
        path: '',
        loadComponent: () => import('./pages/home.component').then((m) => m.HomeComponent),
      },
      {
        path: 'apply',
        data: { title: 'Antrag stellen' },
        loadComponent: () =>
          import('./features/apply/apply-wizard.component').then((m) => m.ApplyWizardComponent),
      },
      {
        path: 'apply/confirmation',
        data: { title: 'Antrag eingegangen' },
        loadComponent: () =>
          import('./features/apply/apply-confirmation.component').then(
            (m) => m.ApplyConfirmationComponent,
          ),
      },
      {
        path: 'status',
        data: { title: 'Antragsstatus' },
        loadComponent: () =>
          import('./features/apply/status-timeline.component').then(
            (m) => m.StatusTimelineComponent,
          ),
      },
      {
        path: 'dashboard',
        data: { title: 'Dashboard' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/dashboard/dashboard.component').then((m) => m.DashboardComponent),
      },
      {
        path: 'applications',
        data: { title: 'Anträge', permission: 'application.read' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/placeholder.component').then((m) => m.PlaceholderComponent),
      },
      {
        path: 'voting',
        data: { title: 'Abstimmungen', permission: ['vote.cast', 'vote.manage'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/placeholder.component').then((m) => m.PlaceholderComponent),
      },
      {
        path: 'meetings',
        data: { title: 'Sitzungen', permission: ['meeting.manage', 'protocol.write'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/placeholder.component').then((m) => m.PlaceholderComponent),
      },
      {
        path: 'budget',
        data: { title: 'Budget', permission: ['budget.view', 'budget.manage'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/placeholder.component').then((m) => m.PlaceholderComponent),
      },
      {
        path: 'admin',
        data: { title: 'Verwaltung', permission: 'admin.config' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/placeholder.component').then((m) => m.PlaceholderComponent),
      },
      {
        path: '**',
        loadComponent: () =>
          import('./pages/not-found.component').then((m) => m.NotFoundComponent),
      },
    ],
  },
];
