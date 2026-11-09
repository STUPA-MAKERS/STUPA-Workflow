import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  effect,
  inject,
  input,
  output,
  untracked,
} from '@angular/core';
import { ToastService } from '@stupa-makers/ui-kit';
import { ServerReachabilityService } from '@core/api/server-reachability.service';
import { I18nService } from '@core/i18n/i18n.service';

/**
 * The load error of a page or a pane (§ 000576, § 000577, § 000579). It renders nothing in
 * the page: while it is in the page, an error toast with `message` and the action "Erneut
 * versuchen" shows. The toast does not close by its time, because it holds the only retry
 * of the page. It closes on the action, on a swipe or its close button, and when the
 * element leaves the page, so a page puts it in the branch of its error state:
 *
 * ```html
 * @if (error()) {
 *   <app-load-error [message]="'x.error' | t" (retry)="reload()" />
 * } @else { … }
 * ```
 *
 * When the load failed because the browser is offline or the server is unreachable
 * ({@link ServerReachabilityService}), the offline bar already names the cause, so no toast
 * shows. When that state ends, the element emits `retry` once, and the page loads again by
 * itself. When the state ends without the server having been unreachable (one route answered
 * 503 for its own reason), the toast shows after all.
 */
@Component({
  selector: 'app-load-error',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '',
  styles: ':host { display: none; }',
})
export class LoadErrorComponent {
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);
  private readonly reach = inject(ServerReachabilityService);

  /** The text of the toast, for example "Anträge konnten nicht geladen werden." */
  readonly message = input.required<string>();
  /** Load the content again: the action of the toast, or the end of the offline state. */
  readonly retry = output<void>();

  private toastId: number | null = null;
  /** The browser was offline or the server unreachable since this error showed. */
  private sawDown = false;
  private done = false;

  constructor() {
    effect(() => {
      const waiting = this.reach.waiting();
      const down = waiting && this.reach.state() !== 'checking';
      untracked(() => this.sync(waiting, down));
    });
    inject(DestroyRef).onDestroy(() => {
      this.done = true;
      this.hide();
    });
  }

  private sync(waiting: boolean, down: boolean): void {
    if (this.done) return;
    if (down) this.sawDown = true;
    if (waiting) {
      this.hide();
      return;
    }
    if (this.sawDown) {
      this.sawDown = false;
      this.retry.emit();
      return;
    }
    this.show();
  }

  private show(): void {
    if (this.toastId !== null) return;
    const action = this.i18n.translate('action.retry');
    this.toastId = this.toast.showAction({
      message: this.message(),
      action,
      actionIcon: 'reload',
      variant: 'danger',
      timeout: 0,
      closed: (how) => {
        this.toastId = null;
        if (how === 'action' && !this.done) this.retry.emit();
      },
    });
  }

  private hide(): void {
    if (this.toastId === null) return;
    const id = this.toastId;
    this.toastId = null;
    this.toast.dismiss(id);
  }
}
