import { render, screen } from '@testing-library/angular';
import { MeetingPageSkeletonComponent } from './meeting-page-skeleton.component';

function setViewport(wide: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: wide && query.includes('min-width: 1200px'),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

describe('MeetingPageSkeletonComponent', () => {
  const realMatchMedia = window.matchMedia;
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => {
    window.matchMedia = realMatchMedia;
  });

  it('is busy and tells a screen reader that the meeting loads', async () => {
    setViewport(true);
    const { container } = await render(MeetingPageSkeletonComponent);
    expect(container.querySelector('.mps__sheet')).toBeTruthy();
    expect(screen.getByRole('status')).toHaveTextContent('Sitzung wird geladen');
  });

  /** The agenda stands beside the sheet only on a wide screen, like on the page. */
  it('draws the agenda beside the sheet on a wide screen', async () => {
    setViewport(true);
    const { container } = await render(MeetingPageSkeletonComponent);
    expect(container.querySelectorAll('.mps__row')).toHaveLength(5);
  });

  it('draws only the sheet below the wide layout', async () => {
    setViewport(false);
    const { container } = await render(MeetingPageSkeletonComponent);
    expect(container.querySelector('.mps__agenda')).toBeNull();
    expect(container.querySelector('.mps__sheet')).toBeTruthy();
  });
});
