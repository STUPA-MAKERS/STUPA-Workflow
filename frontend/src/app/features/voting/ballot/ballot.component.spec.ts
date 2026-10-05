import { Subject, of, throwError } from 'rxjs';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { MyBallot } from '@core/api/models';
import { runAxe } from '../../../../testing/a11y';
import { BallotComponent, type BallotCaster } from './ballot.component';

interface SetupOpts {
  own?: MyBallot | null;
  proxyName?: string | null;
  proxyCast?: boolean;
  secret?: boolean;
  caster?: BallotCaster;
  layout?: 'page' | 'phone';
}

async function setup(opts: SetupOpts = {}) {
  const caster = jest.fn(opts.caster ?? (() => of({ status: 'cast' })));
  const castDone = jest.fn();
  const castFailed = jest.fn();
  const r = await render(BallotComponent, {
    inputs: {
      voteId: 'v1',
      options: ['yes', 'no', 'abstain'],
      own: opts.own === undefined ? { cast: false, choice: null } : opts.own,
      proxyName: opts.proxyName ?? null,
      proxyCast: opts.proxyCast ?? false,
      secret: opts.secret ?? false,
      caster,
      layout: opts.layout ?? 'page',
    },
    on: { castDone, castFailed },
  });
  return { ...r, caster, castDone, castFailed };
}

/** The large choices of the own row. */
const choice = (name: string) =>
  within(screen.getByRole('group', { name: 'Deine Stimme' })).getByRole('button', {
    name: new RegExp(`^${name}$`),
  });
const confirmButton = () => screen.getByRole('button', { name: /abgeben/ });

describe('BallotComponent', () => {
  it('casts in two steps: a pick does not send, the button does', async () => {
    const { caster, castDone } = await setup();
    const user = userEvent.setup();
    expect(confirmButton()).toHaveTextContent('Stimme abgeben');
    expect(confirmButton()).toBeDisabled();

    await user.click(choice('Ja'));
    expect(caster).not.toHaveBeenCalled();
    expect(choice('Ja')).toHaveAttribute('aria-pressed', 'true');
    expect(confirmButton()).toHaveTextContent('Stimme abgeben: Ja');
    expect(screen.getByText('Die Stimme lässt sich danach nicht ändern.')).toBeInTheDocument();

    await user.click(choice('Nein'));
    expect(confirmButton()).toHaveTextContent('Stimme abgeben: Nein');
    await user.click(confirmButton());
    expect(caster).toHaveBeenCalledTimes(1);
    expect(caster).toHaveBeenCalledWith('no', false);
    expect(castDone).toHaveBeenCalledWith({ choice: 'no', asDelegation: false });
  });

  it('sends one ballot on a double click', async () => {
    const pending = new Subject<unknown>();
    const { caster, fixture } = await setup({ caster: () => pending });
    const user = userEvent.setup();
    await user.click(choice('Ja'));
    await user.dblClick(confirmButton());
    expect(caster).toHaveBeenCalledTimes(1);
    // The choices stay off while the ballot is on its way.
    expect(choice('Nein')).toBeDisabled();
    pending.next({ status: 'cast' });
    fixture.detectChanges();
    expect(screen.queryByRole('button', { name: /abgeben/ })).not.toBeInTheDocument();
  });

  it('locks the row after the cast and offers no change', async () => {
    await setup();
    const user = userEvent.setup();
    await user.click(choice('Enthaltung'));
    await user.click(confirmButton());
    expect(screen.getByRole('status')).toHaveTextContent('Danke! Deine Stimme: Enthaltung');
    expect(screen.getByText('Eine Änderung der Stimme ist nicht möglich.')).toBeInTheDocument();
    for (const button of screen.getAllByRole('button')) expect(button).toBeDisabled();
    expect(choice('Enthaltung')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByText(/Stimme ändern/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /abgeben/ })).not.toBeInTheDocument();
  });

  it('starts locked from the server ballot', async () => {
    await setup({ own: { cast: true, choice: 'no' } });
    expect(screen.getByRole('status')).toHaveTextContent('Danke! Deine Stimme: Nein');
    expect(choice('Nein')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByRole('button', { name: /abgeben/ })).not.toBeInTheDocument();
  });

  it('locks on a 409 already_voted, the same as a cast', async () => {
    const error = { status: 409, error: { code: 'already_voted', status: 409, title: 'Conflict' } };
    const { castFailed } = await setup({ caster: () => throwError(() => error) });
    const user = userEvent.setup();
    await user.click(choice('Ja'));
    await user.click(confirmButton());
    expect(castFailed).toHaveBeenCalledWith({ asDelegation: false, alreadyVoted: true, error });
    expect(screen.getByRole('status')).toHaveTextContent('Danke! Deine Stimme ist abgegeben.');
    expect(choice('Ja')).toBeDisabled();
    expect(choice('Ja')).toHaveAttribute('aria-pressed', 'false');
  });

  it('frees the row again on another error, so the person can retry', async () => {
    const error = { status: 500 };
    const { castFailed, caster } = await setup({ caster: () => throwError(() => error) });
    const user = userEvent.setup();
    await user.click(choice('Ja'));
    await user.click(confirmButton());
    expect(castFailed).toHaveBeenCalledWith({ asDelegation: false, alreadyVoted: false, error });
    expect(choice('Ja')).toBeEnabled();
    expect(confirmButton()).toBeEnabled();
    await user.click(confirmButton());
    expect(caster).toHaveBeenCalledTimes(2);
  });

  it('reports a failure without an error object', async () => {
    const { castFailed } = await setup({ caster: () => throwError(() => undefined) });
    const user = userEvent.setup();
    await user.click(choice('Ja'));
    await user.click(confirmButton());
    expect(castFailed).toHaveBeenCalledWith({ asDelegation: false, alreadyVoted: false, error: {} });
  });

  it('casts the represented ballot with asDelegation', async () => {
    const { caster } = await setup({ proxyName: 'Jonas Weber' });
    const user = userEvent.setup();
    expect(screen.getByRole('heading', { name: 'Deine Stimme' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Als Vertretung für Jonas Weber' })).toBeInTheDocument();
    const proxyGroup = screen.getByRole('group', { name: 'Als Vertretung für Jonas Weber' });
    const proxyNo = proxyGroup.querySelectorAll('button')[1];
    await user.click(proxyNo);
    expect(proxyNo).toHaveAttribute('aria-pressed', 'true');
    expect(confirmButton()).toHaveTextContent('Für Jonas Weber abgeben: Nein');
    await user.click(confirmButton());
    expect(caster).toHaveBeenCalledWith('no', true);
    expect(screen.getByText('Für Jonas Weber abgegeben: Nein')).toBeInTheDocument();
    // The own row stays open, and the button moves to it.
    expect(confirmButton()).toHaveTextContent('Stimme abgeben');
    await user.click(choice('Ja'));
    await user.click(confirmButton());
    expect(caster).toHaveBeenLastCalledWith('yes', false);
    expect(screen.queryByRole('button', { name: /abgeben/ })).not.toBeInTheDocument();
  });

  it('moves the button to the proxy row once the own ballot is in', async () => {
    await setup({ own: { cast: true, choice: 'yes' }, proxyName: 'Jonas Weber' });
    expect(confirmButton()).toHaveTextContent('Für Jonas Weber abgeben');
    expect(confirmButton()).toBeDisabled();
  });

  it('shows the represented ballot locked from the server', async () => {
    await setup({ proxyName: 'Jonas Weber', proxyCast: true, own: null });
    expect(screen.getByText('Für Jonas Weber abgegeben.')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Deine Stimme' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /abgeben/ })).not.toBeInTheDocument();
  });

  it('never shows the choice of a secret ballot', async () => {
    const { caster } = await setup({ secret: true, proxyName: 'Jonas Weber' });
    const user = userEvent.setup();
    await user.click(choice('Nein'));
    await user.click(confirmButton());
    expect(caster).toHaveBeenCalledWith('no', false);
    expect(screen.getByText('Danke! Deine Stimme ist abgegeben.')).toBeInTheDocument();
    expect(screen.queryByText(/Deine Stimme: Nein/)).not.toBeInTheDocument();
    expect(choice('Nein')).toHaveAttribute('aria-pressed', 'false');
    const proxyYes = screen.getByRole('group', { name: /Vertretung/ }).querySelector('button');
    await user.click(proxyYes as HTMLElement);
    await user.click(confirmButton());
    expect(screen.getByText('Für Jonas Weber abgegeben.')).toBeInTheDocument();
  });

  it('shows no own row without a voting right', async () => {
    await setup({ own: null });
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('clears the picks and the local lock for a new vote', async () => {
    const { fixture } = await setup();
    const user = userEvent.setup();
    await user.click(choice('Ja'));
    await user.click(confirmButton());
    expect(choice('Ja')).toBeDisabled();
    fixture.componentRef.setInput('voteId', 'v2');
    fixture.detectChanges();
    expect(choice('Ja')).toBeEnabled();
    expect(choice('Ja')).toHaveAttribute('aria-pressed', 'false');
  });

  it('names the rows and keeps room for the pinned bar on a phone', async () => {
    let callback: ResizeObserverCallback = () => {};
    const original = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class {
      constructor(cb: ResizeObserverCallback) {
        callback = cb;
      }
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    } as unknown as typeof ResizeObserver;
    try {
      const { fixture, container } = await setup({ layout: 'phone' });
      expect(container.firstElementChild ?? fixture.nativeElement).toBeTruthy();
      expect(fixture.nativeElement).toHaveClass('ballot--phone');
      expect(screen.getByRole('heading', { name: 'Deine Stimme' })).toBeInTheDocument();
      const bar = fixture.nativeElement.querySelector('.ballot__bar') as HTMLElement;
      Object.defineProperty(bar, 'offsetHeight', { value: 96 });
      callback([], {} as ResizeObserver);
      fixture.detectChanges();
      const spacer = fixture.nativeElement.querySelector('.ballot__spacer') as HTMLElement;
      expect(spacer.style.height).toBe('96px');
    } finally {
      globalThis.ResizeObserver = original;
    }
  });

  it('works without ResizeObserver', async () => {
    const original = globalThis.ResizeObserver;
    // @ts-expect-error -- a browser without the API
    delete globalThis.ResizeObserver;
    try {
      const { fixture } = await setup({ layout: 'phone' });
      expect(fixture.nativeElement.querySelector('.ballot__spacer')).toBeTruthy();
    } finally {
      globalThis.ResizeObserver = original;
    }
  });

  it('ignores a pick and a confirm that cannot apply', async () => {
    const { fixture, caster } = await setup({ own: { cast: true, choice: 'yes' } });
    const cmp = fixture.componentInstance as unknown as {
      pick(row: 'own' | 'proxy', o: string): void;
      confirm(): void;
    };
    cmp.pick('own', 'no');
    cmp.pick('proxy', 'no');
    cmp.confirm();
    expect(caster).not.toHaveBeenCalled();
  });

  it('ignores a confirm without a pick', async () => {
    const { fixture, caster } = await setup();
    (fixture.componentInstance as unknown as { confirm(): void }).confirm();
    expect(caster).not.toHaveBeenCalled();
  });

  it('has no a11y violations', async () => {
    const { container } = await setup({ proxyName: 'Jonas Weber' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
