import { InjectionToken, type Signal } from '@angular/core';

/**
 * The link from the detail of `/my-applications/<id>` to its list page: the detail reads
 * whether the list sits beside it, as the detail of the list "Anträge" does through
 * `ApplicationsPageService`. A detail without the list page (the old view of one Antrag)
 * finds no provider.
 */
export interface MyApplicationsPage {
  /** The list and the detail sit side by side. */
  readonly split: Signal<boolean>;
  /** Reload the list after a change in the detail. */
  reload(): void;
}

export const MY_APPLICATIONS_PAGE = new InjectionToken<MyApplicationsPage>('MY_APPLICATIONS_PAGE');
