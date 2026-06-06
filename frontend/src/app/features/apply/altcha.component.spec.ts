import { render, screen } from '@testing-library/angular';
import { AltchaComponent } from './altcha.component';

describe('AltchaComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('renders the idle label in English when the locale is EN', async () => {
    localStorage.setItem('ap.locale', 'en');
    await render(AltchaComponent, { on: { solved: jest.fn() } });
    expect(screen.getByRole('button', { name: /not a robot/i })).toBeInTheDocument();
  });

  it('emits a solution once the challenge is solved', async () => {
    jest.useFakeTimers();
    const solved = jest.fn();
    const { fixture } = await render(AltchaComponent, { on: { solved } });

    const btn = screen.getByRole('button', { name: /kein Roboter/i });
    btn.click();

    jest.advanceTimersByTime(300);
    fixture.detectChanges();
    expect(solved).toHaveBeenCalledWith('altcha-stub-solution');
    expect(screen.getByText(/Bestätigt/)).toBeInTheDocument();
    jest.useRealTimers();
  });

  it('ignores repeated clicks while verifying', async () => {
    jest.useFakeTimers();
    const solved = jest.fn();
    await render(AltchaComponent, { on: { solved } });
    const btn = screen.getByRole('button');
    btn.click();
    btn.click();
    jest.advanceTimersByTime(300);
    expect(solved).toHaveBeenCalledTimes(1);
    jest.useRealTimers();
  });
});
