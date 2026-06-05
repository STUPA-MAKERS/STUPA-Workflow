import { provideRouter } from '@angular/router';
import { render } from '@testing-library/angular';
import { App } from './app';

describe('App', () => {
  it('mounts and exposes the router outlet', async () => {
    const { container } = await render(App, { providers: [provideRouter([])] });
    expect(container.querySelector('router-outlet')).not.toBeNull();
  });
});
