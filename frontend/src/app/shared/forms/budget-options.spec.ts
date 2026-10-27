import { budgetOptionTree } from './budget-options';

describe('budgetOptionTree', () => {
  it('nests the options by their parent and splits the label into name and path key', () => {
    const tree = budgetOptionTree(
      [
        { value: 'a', label: { de: 'AStA (VS)', en: 'AStA (VS)' }, key: 'VS', color: '#111111' },
        { value: 'b', label: { de: 'Kultur (Events) (VS-1)' }, key: '1', parentId: 'a' },
        { value: 'c', label: { de: 'Sport (VS-1-2)' }, key: '2', parentId: 'b' },
      ],
      'de',
    );
    expect(tree).toHaveLength(1);
    const [a] = tree;
    expect([a.name, a.pathKey, a.key, a.color, a.parentId]).toEqual([
      'AStA',
      'VS',
      'VS',
      '#111111',
      null,
    ]);
    const [b] = a.children;
    expect([b.name, b.pathKey, b.color]).toEqual(['Kultur (Events)', 'VS-1', null]);
    expect(b.children.map((c) => c.id)).toEqual(['c']);
    expect(b.byFiscalYear).toEqual([]);
  });

  it('makes an option without a known parent a root and takes a plain label as the name', () => {
    const tree = budgetOptionTree(
      [
        { value: 'x', label: { de: 'Ohne Schlüssel' }, parentId: 'gone' },
        { value: 'y', label: { de: 'Zweite (Z)' } },
      ],
      'de',
    );
    expect(tree.map((n) => [n.id, n.name, n.pathKey, n.key, n.parentId])).toEqual([
      ['x', 'Ohne Schlüssel', '', '', null],
      ['y', 'Zweite', 'Z', '', null],
    ]);
  });
});
