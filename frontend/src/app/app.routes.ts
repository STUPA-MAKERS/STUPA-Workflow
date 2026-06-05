import type { Routes } from '@angular/router';
import { ShellComponent } from './layout/shell.component';

/**
 * Routing-Gerüst (T-03). Feature-Routen laden vorerst einen Platzhalter; die
 * echten Feature-Module folgen in T-30…T-36 (loadChildren je Feature).
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
          import('./pages/placeholder.component').then((m) => m.PlaceholderComponent),
      },
      {
        path: 'dashboard',
        data: { title: 'Dashboard' },
        loadComponent: () =>
          import('./pages/placeholder.component').then((m) => m.PlaceholderComponent),
      },
      {
        path: 'applications',
        data: { title: 'Anträge' },
        loadComponent: () =>
          import('./pages/placeholder.component').then((m) => m.PlaceholderComponent),
      },
      {
        path: 'voting',
        data: { title: 'Abstimmungen' },
        loadComponent: () =>
          import('./pages/placeholder.component').then((m) => m.PlaceholderComponent),
      },
      {
        path: 'meetings',
        data: { title: 'Sitzungen' },
        loadComponent: () =>
          import('./pages/placeholder.component').then((m) => m.PlaceholderComponent),
      },
      {
        path: 'budget',
        data: { title: 'Budget' },
        loadComponent: () =>
          import('./pages/placeholder.component').then((m) => m.PlaceholderComponent),
      },
      {
        path: 'admin',
        data: { title: 'Verwaltung' },
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
