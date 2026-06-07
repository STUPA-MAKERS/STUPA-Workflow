/**
 * Mock-Seed-Daten für den Admin-Bereich (T-34). Nur aktiv, solange T-24
 * (admin-API) + #21 (site-config) nicht real gemergt sind (`USE_MOCK_API`).
 * Beim Backend-Merge entfällt diese Datei zusammen mit den Mock-Zweigen im
 * `AdminApiService`.
 */
import type { Branding, Gremium, NotificationRule, WebhookConfig } from './admin.models';

export const MOCK_GREMIEN: Gremium[] = [
  { id: 'g-stupa', name: 'Studierendenparlament', slug: 'stupa', cdVariant: 'stupa', defaultLang: 'de' },
  { id: 'g-asta', name: 'AStA', slug: 'asta', cdVariant: 'asta', defaultLang: 'de' },
];

export const MOCK_WEBHOOKS: WebhookConfig[] = [
  {
    id: 'wh-1',
    name: 'Matrix-Bridge',
    url: 'https://hooks.example.org/matrix',
    events: ['application_created', 'status_changed'],
    active: true,
  },
];

export const MOCK_NOTIFICATION_RULES: NotificationRule[] = [
  {
    id: 'nr-1',
    event: 'status_changed',
    recipients: [{ kind: 'applicant' }],
    templateKey: 'status_changed_applicant',
    enabled: true,
  },
];

export const MOCK_BRANDING: Branding = {
  logos: {},
  footerColumns: [
    {
      label: { de: 'Über uns', en: 'About' },
      links: [{ label: { de: 'Impressum', en: 'Imprint' }, url: 'https://example.org/impressum' }],
    },
  ],
  copyright: { de: '© Studierendenschaft', en: '© Student body' },
  legalLinks: [{ label: { de: 'Datenschutz', en: 'Privacy' }, url: 'https://example.org/privacy' }],
  freetexts: {
    loginHint: { de: 'Mit Hochschul-Account anmelden.', en: 'Sign in with your university account.' },
    welcome: { de: 'Willkommen auf der Antragsplattform.', en: 'Welcome to the application platform.' },
    support: { de: 'Bei Fragen: support@example.org', en: 'Questions? support@example.org' },
    emailFooter: { de: 'Automatische Nachricht – nicht antworten.', en: 'Automated message – do not reply.' },
  },
};
