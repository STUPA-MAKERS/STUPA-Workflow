import { render } from '@testing-library/angular';
import { runAxe } from '../../../../testing/a11y';
import { DropOverlayComponent } from './drop-overlay.component';

describe('DropOverlayComponent', () => {
  it('shows the line, hidden from screen readers, over its parent', async () => {
    const view = await render(DropOverlayComponent, { inputs: { label: 'Dateien ablegen' } });
    const host = view.container.querySelector('app-drop-overlay') ?? view.fixture.nativeElement;
    expect(host).toHaveTextContent('Dateien ablegen');
    expect(host).toHaveAttribute('aria-hidden', 'true');
    expect(host).not.toHaveClass('drop--view');
    expect((host as HTMLElement).style.top).toBe('');
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('covers the part of its parent on the screen with fit="view"', async () => {
    const view = await render(
      `<div id="parent"><app-drop-overlay fit="view" label="Ablegen" /></div>`,
      {
        imports: [DropOverlayComponent],
        configureTestBed: () => {
          jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
            top: -200,
            left: 80,
            bottom: 5000,
            right: 900,
          } as DOMRect);
          Object.defineProperty(window, 'innerHeight', { value: 768, configurable: true });
          Object.defineProperty(window, 'innerWidth', { value: 1024, configurable: true });
        },
      },
    );
    await view.fixture.whenStable();
    view.fixture.detectChanges();
    const host = view.container.querySelector('app-drop-overlay') as HTMLElement;
    expect(host).toHaveClass('drop--view');
    expect(host.style.top).toBe('0px');
    expect(host.style.left).toBe('80px');
    expect(host.style.width).toBe('820px');
    expect(host.style.height).toBe('768px');
  });
});
