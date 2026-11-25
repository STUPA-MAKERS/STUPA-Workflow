import { inject } from '@angular/core';
import { type CanActivateFn, Router } from '@angular/router';

/**
 * The two addresses of the page "Veranstaltungen" that carry their target in the query:
 * `/events?id=<id>` opens the Event (spec 003027), and `/events?new=event` opens the form
 * of a new Event. The pane of the page is a child route, so the guard leads each of them
 * to its child address and keeps the other parameters.
 */
export const eventAddress: CanActivateFn = (route) => {
  const query = route.queryParams;
  const id = typeof query['id'] === 'string' ? query['id'] : '';
  const isNew = query['new'] === 'event';
  if (!id && !isNew) return true;
  const rest = Object.fromEntries(
    Object.entries(query).filter(([key]) => key !== 'id' && key !== 'new'),
  );
  return inject(Router).createUrlTree(['/events', isNew ? 'new' : id], { queryParams: rest });
};
