import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';
import { loadCatalog } from './app/core/i18n/translations';

// The DE texts are a lazy chunk (spec 002003). Start the load before the app boots, so it
// runs beside the boot; the app initializer waits for the same load.
void loadCatalog('de').catch(() => undefined);

// iOS Safari sets :active on a touched element only while a touch listener exists on the
// page. The press state of the controls (`_press.scss` of the ui-kit) is the only feedback
// of a tap, so an empty passive listener turns it on. Passive: it never delays a scroll.
document.addEventListener('touchstart', () => undefined, { passive: true });

bootstrapApplication(App, appConfig)
  .catch((err) => console.error(err));
