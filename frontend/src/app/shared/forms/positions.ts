/**
 * The cost positions of a `positions` answer (Kostenaufstellung).
 *
 * The server checks the shape (forms/validation.py `_validate_positions`): a position has
 * a label and offers; exactly one offer is preferred, and its value is the value of the
 * position. A position can opt out of comparison offers (`noOffers`) with a reason; it
 * then needs exactly one offer. The total of all positions goes into `amount`.
 *
 * Comparison offers stay tagged attachments (O5): an offer has no file reference.
 */

/** One offer of a position. */
export interface PositionOffer {
  label: string;
  value: number | null;
  preferred: boolean;
}

/** One cost position with its offers. */
export interface CostPosition {
  label: string;
  offers: PositionOffer[];
  /** The position has no comparison offers; `noOffersReason` says why. */
  noOffers: boolean;
  noOffersReason: string;
}

function toNumber(raw: unknown): number | null {
  if (raw === null || raw === undefined || raw === '' || typeof raw === 'boolean') return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

/**
 * Read a stored `positions` answer into typed positions. Anything that is no list gives
 * no positions; a broken entry keeps what it has, so an old answer still shows.
 */
export function normalizePositions(raw: unknown): CostPosition[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((p): p is Record<string, unknown> => typeof p === 'object' && p !== null)
    .map((p) => ({
      label: typeof p['label'] === 'string' ? p['label'] : '',
      offers: (Array.isArray(p['offers']) ? p['offers'] : [])
        .filter((o): o is Record<string, unknown> => typeof o === 'object' && o !== null)
        .map((o) => ({
          label: typeof o['label'] === 'string' ? o['label'] : '',
          value: toNumber(o['value']),
          preferred: o['preferred'] === true,
        })),
      noOffers: p['noOffers'] === true,
      noOffersReason: typeof p['noOffersReason'] === 'string' ? p['noOffersReason'] : '',
    }));
}

/** The preferred offer of a position, or undefined. */
export function preferredOffer(p: Pick<CostPosition, 'offers'>): PositionOffer | undefined {
  return p.offers.find((o) => o.preferred);
}

/** The value of a position: the value of its preferred offer, else 0. */
export function positionValue(p: Pick<CostPosition, 'offers'>): number {
  return preferredOffer(p)?.value ?? 0;
}

/** The sum of all position values. */
export function positionsTotal(positions: readonly Pick<CostPosition, 'offers'>[]): number {
  return positions.reduce((sum, p) => sum + positionValue(p), 0);
}
