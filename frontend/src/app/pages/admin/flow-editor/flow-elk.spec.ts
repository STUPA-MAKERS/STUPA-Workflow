import { TestBed } from '@angular/core/testing';
import type { ElkNode } from 'elkjs/lib/elk-api';
import {
  FLOW_LAYOUTER,
  type LayoutInput,
  type LayoutLink,
  bundleLabel,
  bundles,
  elkGraph,
  layoutLevel,
  readLayout,
  roundedPath,
  textWidth,
} from './flow-elk';

const many = (n: number): string => `${n} Übergänge`;

const link = (index: number, src: string, dst: string, label = '', port = 'out'): LayoutLink => ({
  index,
  src,
  port,
  dst,
  label,
  automatic: false,
});

/** a → b (two named), a → c (three), b → c (one automatic, no name). */
const INPUT: LayoutInput = {
  boxes: [
    { id: 'a', w: 150, h: 96, ports: [
      { id: 'out', y: 26, label: '' },
      { id: 'g1', y: 48, label: 'Rolle ist: Referent' },
      { id: 'g2', y: 70, label: 'Antragsart ist: qsm' },
    ] },
    { id: 'b', w: 150, h: 52, ports: [{ id: 'out', y: 26, label: '' }] },
    { id: 'c', w: 150, h: 52, ports: [] },
  ],
  links: [
    link(0, 'a', 'b', 'Freigeben'),
    link(1, 'a', 'b', 'Ablehnen', 'g1'),
    link(2, 'a', 'c', 'x', 'g1'),
    link(3, 'a', 'c', '', 'g2'),
    link(4, 'a', 'c', 'z'),
    { ...link(5, 'b', 'c'), automatic: true },
  ],
};

describe('flow-elk', () => {
  /** jsdom has no 2D canvas, so the estimate grows with the length and the size. */
  it('measures a text without a canvas from its length and the font size', () => {
    expect(textWidth('', '12px x')).toBe(0);
    expect(textWidth('abcd', '10px x')).toBeLessThan(textWidth('abcdefgh', '10px x'));
    expect(textWidth('abcd', '10px x')).toBeLessThan(textWidth('abcd', '20px x'));
    expect(textWidth('abcd', 'bold x')).toBeGreaterThan(0);
  });

  it('measures a text with an offscreen canvas where there is one', () => {
    const ctx = { font: '', measureText: jest.fn((t: string) => ({ width: t.length * 7.2 })) };
    const g = globalThis as unknown as { OffscreenCanvas?: unknown };
    g.OffscreenCanvas = class {
      getContext(): unknown {
        return ctx;
      }
    };
    try {
      jest.isolateModules(() => {
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const m = require('./flow-elk') as typeof import('./flow-elk');
        expect(m.textWidth('abc', '600 13.5px x')).toBe(22);
        expect(ctx.font).toBe('600 13.5px x');
      });
    } finally {
      delete g.OffscreenCanvas;
    }
  });

  it('bundles the transitions of one source and target, whatever the dot', () => {
    const b = bundles(INPUT.links);
    expect(b.map((x) => x.map((l) => l.index))).toEqual([[0, 1], [2, 3, 4], [5]]);
    expect(bundleLabel(b[0], many)).toBe('Freigeben · Ablehnen');
    expect(bundleLabel(b[1], many)).toBe('3 Übergänge');
    expect(bundleLabel(b[2], many)).toBe('');
    expect(bundleLabel([link(0, 'a', 'b', 'A'), link(1, 'a', 'b')], many)).toBe('2 Übergänge');
  });

  /** A short leg limits the radius to half its length. */
  it('rounds the corners of a right-angled path and drops repeated points', () => {
    expect(roundedPath([])).toBe('');
    expect(roundedPath([{ x: 0, y: 0 }])).toBe('M 0 0');
    expect(roundedPath([{ x: 0, y: 0 }, { x: 0, y: 0 }, { x: 10, y: 0 }])).toBe('M 0 0 L 10 0');
    expect(roundedPath([{ x: 0, y: 0 }, { x: 40, y: 0 }, { x: 40, y: 40 }])).toBe(
      'M 0 0 L 30 0 Q 40 0, 40 10 L 40 40',
    );
    expect(roundedPath([{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 4, y: 40 }])).toBe(
      'M 0 0 L 2 0 Q 4 0, 4 2 L 4 40',
    );
  });

  /**
   * An automatic transition without a name still gets room for its bolt. For a dot that is not
   * drawn, the line starts at the box itself.
   */
  it('builds the ELK graph: fixed dots, one label per bundle, proxies in the outer layers', () => {
    const g = elkGraph(
      {
        boxes: [
          { id: 'p', w: 150, h: 44, ports: [{ id: 'out', y: 22, label: '' }], layer: 'first' },
          ...INPUT.boxes,
          { id: 'q', w: 150, h: 44, ports: [], layer: 'last' },
        ],
        links: [...INPUT.links, link(6, 'c', 'q', '', 'none')],
      },
      many,
    );
    const p = g.children!.find((c) => c.id === 'p')!;
    expect(p.layoutOptions!['elk.layered.layering.layerConstraint']).toBe('FIRST');
    const q = g.children!.find((c) => c.id === 'q')!;
    expect(q.layoutOptions!['elk.layered.layering.layerConstraint']).toBe('LAST');
    const a = g.children!.find((c) => c.id === 'a')!;
    expect(a.ports!.map((x) => x.id)).toEqual(['a::in', 'a::out', 'a::g1', 'a::g2']);
    expect(a.ports![2].labels![0].text).toBe('Rolle ist: Referent');
    expect(a.ports![1].labels).toEqual([]);
    const e = new Map(g.edges!.map((x) => [x.id, x]));
    expect(e.get('t0')!.labels![0].text).toBe('Freigeben · Ablehnen');
    expect(e.get('t1')!.labels).toEqual([]);
    expect(e.get('t2')!.labels![0].text).toBe('3 Übergänge');
    expect(e.get('t1')!.sources).toEqual(['a::g1']);
    expect(e.get('t1')!.targets).toEqual(['b::in']);
    expect(e.get('t5')!.labels![0].text).toBe('');
    expect(e.get('t5')!.labels![0].width).toBeGreaterThan(10);
    expect(e.get('t6')!.sources).toEqual(['c']);
  });

  /** A label without a place gives no label. */
  it('reads the places and the lines back; a line without a section is left out', () => {
    const out: ElkNode = {
      id: 'root',
      children: [
        { id: 'a', x: 10.4, y: 20.6 },
        { id: 'b' },
      ],
      edges: [
        {
          id: 't0',
          sources: [],
          targets: [],
          labels: [{ x: 50, y: 10, width: 40, height: 16 }],
          sections: [{ id: 's', startPoint: { x: 0, y: 0 }, endPoint: { x: 100, y: 0 } }],
        },
        {
          id: 't1',
          sources: [],
          targets: [],
          sections: [
            { id: 's', startPoint: { x: 0, y: 20 }, bendPoints: [{ x: 50, y: 20 }, { x: 50, y: 0 }], endPoint: { x: 100, y: 0 } },
          ],
        },
        { id: 't2', sources: [], targets: [], labels: [{ width: 10, height: 10 }], sections: [{ id: 's', startPoint: { x: 0, y: 0 }, endPoint: { x: 1, y: 0 } }] },
      ],
    };
    const r = readLayout(INPUT, out, many);
    expect(r.pos.get('a')).toEqual({ x: 10, y: 21 });
    expect(r.pos.get('b')).toEqual({ x: 0, y: 0 });
    expect(r.routes.get(0)).toEqual({
      d: 'M 0 0 L 100 0',
      label: { x: 70, y: 18, text: 'Freigeben · Ablehnen' },
      bundle: [0, 1],
    });
    expect(r.routes.get(1)!.label).toBeNull();
    expect(r.routes.get(1)!.d).toContain('Q 50 20');
    expect(r.routes.get(2)!.label).toBeNull();
    expect(r.routes.has(3)).toBe(false);
  });

  it('lays out a level with elkjs: left to right, every line routed', async () => {
    const r = await layoutLevel(INPUT, many);
    const a = r.pos.get('a')!;
    const b = r.pos.get('b')!;
    const c = r.pos.get('c')!;
    expect(a.x).toBeLessThan(b.x);
    expect(b.x).toBeLessThan(c.x);
    for (const i of [0, 1, 2, 3, 4, 5]) expect(r.routes.get(i)!.d).toMatch(/^M /);
    expect(r.routes.get(2)!.label!.text).toBe('3 Übergänge');
    expect(r.routes.get(3)!.label).toBeNull();
  });

  it('provides layoutLevel as the default layouter', () => {
    expect(TestBed.inject(FLOW_LAYOUTER)).toBe(layoutLevel);
  });
});
