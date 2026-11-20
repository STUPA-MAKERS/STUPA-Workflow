import { figureColumns, figureMinRem } from './figure-grid.util';

describe('figureColumns', () => {
  it('has no count while the width is not measured', () => {
    expect(figureColumns(7, 0, 150)).toBeNull();
    expect(figureColumns(0, 600, 150)).toBeNull();
  });

  it('spreads the figures evenly over the rows', () => {
    expect(figureColumns(7, 780, 150)).toBe(4); // five fit: 4 + 3, not 5 + 2
    expect(figureColumns(6, 780, 150)).toBe(3); // five fit: 3 + 3, not 5 + 1
    expect(figureColumns(6, 1000, 150)).toBe(6);
    expect(figureColumns(3, 1000, 150)).toBe(3);
  });

  it('keeps one column when not even one fits', () => {
    expect(figureColumns(6, 100, 150)).toBe(1);
  });
});

describe('figureMinRem', () => {
  it('is as wide as the amount, at least ten characters', () => {
    expect(figureMinRem(8)).toBe(8.75);
    expect(figureMinRem(12)).toBeCloseTo(10.1);
  });
});
