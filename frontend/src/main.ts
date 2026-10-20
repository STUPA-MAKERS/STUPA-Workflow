import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';

// iOS Safari sets :active on a touched element only while a touch listener exists on the
// page. The press state of the controls (`_press.scss` of the ui-kit) is the only feedback
// of a tap, so an empty passive listener turns it on. Passive: it never delays a scroll.
document.addEventListener('touchstart', () => undefined, { passive: true });

bootstrapApplication(App, appConfig)
  .catch((err) => console.error(err));
