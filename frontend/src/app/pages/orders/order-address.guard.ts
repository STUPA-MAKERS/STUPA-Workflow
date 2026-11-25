import { inject } from '@angular/core';
import { type CanActivateFn, Router } from '@angular/router';

/**
 * The two addresses of the page "Bestellungen" that carry their target in the query:
 * `/orders?id=<id>` opens the Bestellung, and `/orders?new=order&application=<id>` opens
 * the form of a new Bestellung for this Antrag. The pane of the page is a child route, so
 * the guard leads each of them to its child address and keeps the other parameters.
 */
export const orderAddress: CanActivateFn = (route) => {
  const query = route.queryParams;
  const id = typeof query['id'] === 'string' ? query['id'] : '';
  const isNew = query['new'] === 'order';
  if (!id && !isNew) return true;
  const rest = Object.fromEntries(
    Object.entries(query).filter(([key]) => key !== 'id' && key !== 'new'),
  );
  return inject(Router).createUrlTree(['/orders', isNew ? 'new' : id], { queryParams: rest });
};
