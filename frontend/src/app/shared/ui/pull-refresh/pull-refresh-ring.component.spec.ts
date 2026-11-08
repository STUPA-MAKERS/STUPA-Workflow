import { render } from '@testing-library/angular';
import { runAxe } from '../../../../testing/a11y';
import { PullRefreshRingComponent } from './pull-refresh-ring.component';

describe('PullRefreshRingComponent', () => {
  /** § NF/accessibility/conformance/000493: the ring is for the eye only, in rest and in spin. */
  it('has no axe violations and is hidden from screen readers', async () => {
    const view = await render(PullRefreshRingComponent);
    const ring = view.fixture.componentInstance;
    expect(view.fixture.nativeElement).toHaveAttribute('aria-hidden', 'true');
    ring.paint(0, 40, 0.5, 0);
    expect(await runAxe(view.container)).toHaveNoViolations();
    ring.spin(true);
    expect(await runAxe(view.container)).toHaveNoViolations();
  });
});
