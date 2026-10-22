import { Component, signal } from '@angular/core';
import { render } from '@testing-library/angular';
import { BodyPortalDirective } from './body-portal.directive';

@Component({
  standalone: true,
  imports: [BodyPortalDirective],
  template: `
    <div class="clip">
      @if (shown()) {
        <p class="moved" appBodyPortal>Dialog</p>
      }
    </div>
  `,
})
class HostComponent {
  readonly shown = signal(true);
}

describe('BodyPortalDirective', () => {
  it('moves the host to the end of the body', async () => {
    const { container } = await render(HostComponent);
    const moved = document.querySelector('.moved');
    expect(moved?.parentElement).toBe(document.body);
    expect(container.querySelector('.clip .moved')).toBeNull();
  });

  it('removes the host when its block goes away', async () => {
    const { fixture } = await render(HostComponent);
    fixture.componentInstance.shown.set(false);
    fixture.detectChanges();
    expect(document.querySelector('.moved')).toBeNull();
  });

  it('removes the host when the declaring view is destroyed', async () => {
    const { fixture } = await render(HostComponent);
    fixture.destroy();
    expect(document.querySelector('.moved')).toBeNull();
  });
});
