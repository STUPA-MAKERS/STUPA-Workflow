/**
 * The columns of the figure grid of the budget sheet. As many columns as fit, but spread
 * evenly over the rows: seven figures that fit five to a row stand as four and three, not
 * five and two, and six stand as three and three. Every row has the same column grid, so the
 * lines between the figures stand over each other.
 *
 * @param count the number of figures.
 * @param width the inner width of the grid in CSS pixels; 0 when it is not measured yet.
 * @param minWidth the narrowest column in CSS pixels.
 * @returns the number of columns, or null while the width is unknown (the grid then fits as
 *   many columns as it can by itself).
 */
export function figureColumns(count: number, width: number, minWidth: number): number | null {
  if (width <= 0 || count <= 0) return null;
  const fit = Math.max(1, Math.min(count, Math.floor(width / minWidth)));
  const rows = Math.ceil(count / fit);
  return Math.ceil(count / rows);
}

/** The narrowest column for amounts of `chars` characters, in rem: the mono face is 0.6em
 *  wide per character at 1.125rem, plus the padding of a tile (2 × 0.75rem) and some room. */
export function figureMinRem(chars: number): number {
  return Math.max(10, chars) * 0.675 + 2;
}
