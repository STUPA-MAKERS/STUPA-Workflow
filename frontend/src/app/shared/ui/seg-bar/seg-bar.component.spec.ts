import { render, screen } from '@testing-library/angular';
import { runAxe } from '../../../../testing/a11y';
import { SegBarComponent, type Seg } from './seg-bar.component';

describe('SegBarComponent', () => {
  async function setup(segments: Seg[], extra: Record<string, unknown> = {}) {
    const view = await render(SegBarComponent, {
      inputs: { segments, label: '1.250 € von 4.000 € ausgegeben', ...extra },
    });
    const host = view.fixture.nativeElement as HTMLElement;
    const parts = Array.from(host.querySelectorAll<HTMLElement>('.bar__seg:not(.bar__rest)'));
    return { view, host, parts, rest: host.querySelector('.bar__rest') };
  }

  it('is one picture with a label that says the numbers', async () => {
    const { view } = await setup([{ value: 1250, tone: 'filled' }], { total: 4000 });
    expect(screen.getByRole('img', { name: '1.250 € von 4.000 € ausgegeben' })).toBeTruthy();
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('gives each part its share of the total and leaves a grey rest', async () => {
    const { parts, rest } = await setup(
      [
        { value: 1000, tone: 'filled' },
        { value: 1000, tone: 'second' },
      ],
      { total: 4000 },
    );
    expect(parts.map((p) => p.style.flexBasis)).toEqual(['25%', '25%']);
    expect(parts[0]).toHaveClass('bar__seg--filled');
    expect(parts[1]).toHaveClass('bar__seg--second');
    expect(rest).toBeTruthy();
  });

  it('scales to the sum when the parts exceed the total, without a rest', async () => {
    const { parts, rest } = await setup(
      [
        { value: 4000, tone: 'filled' },
        { value: 1000, tone: 'error' },
      ],
      { total: 4000 },
    );
    expect(parts.map((p) => p.style.flexBasis)).toEqual(['80%', '20%']);
    expect(rest).toBeNull();
  });

  it('lets the parts fill the bar together without a total', async () => {
    const { parts, rest } = await setup([
      { value: 15, tone: 'filled' },
      { value: 3, tone: 'error' },
      { value: 2, tone: 'muted' },
    ]);
    expect(parts.map((p) => p.style.flexBasis)).toEqual(['75%', '15%', '10%']);
    expect(rest).toBeNull();
  });

  it('leaves out empty parts and shows an empty bar as all rest', async () => {
    const { parts, rest } = await setup([{ value: 0, tone: 'filled' }], { total: 0 });
    expect(parts).toHaveLength(0);
    expect(rest).toBeTruthy();
  });

  it('carries the size class', async () => {
    const { host } = await setup([{ value: 1, tone: 'filled' }], { size: 'thin' });
    expect(host).toHaveClass('bar--thin');
  });
});
