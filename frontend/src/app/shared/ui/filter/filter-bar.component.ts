import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent } from '../button/button.component';
import { IconComponent } from '../icon/icon.component';

/**
 * Einheitlicher Filter-Balken für Listen (#filters). Ein sekundärer Button
 * (Trichter-Icon + Label + Aktiv-Zähler) öffnet ein rechtsbündiges Popover; die
 * eigentlichen Filter-Felder werden projiziert (`<app-filter-field>` /
 * `<app-filter-range>`). Schließt bei Klick außerhalb und Escape.
 *
 * Zwei Modi:
 * - **Apply** (Default): Popover zeigt „Anwenden" + „Zurücksetzen"; der Konsument
 *   übernimmt die Werte erst bei `(apply)`.
 * - **Live** (`[live]="true"`): keine Anwenden-Taste — Felder wirken sofort (der
 *   Konsument bindet direkt). Nur „Zurücksetzen" erscheint bei aktiven Filtern.
 */
@Component({
  selector: 'app-filter-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ButtonComponent, IconComponent],
  template: `
    <div class="filter">
      <app-button
        variant="secondary"
        size="sm"
        [attr.aria-expanded]="open()"
        (click)="toggle()"
      >
        <span class="filter__btn">
          <app-icon name="filter" [size]="16" />
          {{ label() || ('filter.button' | t) }}
          @if (activeCount() > 0) {
            <span class="filter__count" aria-hidden="true">{{ activeCount() }}</span>
          }
        </span>
      </app-button>

      @if (open()) {
        <div class="filter__panel" role="dialog" [attr.aria-label]="label() || ('filter.button' | t)">
          <div class="filter__fields">
            <ng-content />
          </div>
          <div class="filter__actions">
            @if (!live()) {
              <app-button size="sm" (click)="emitApply()">
                {{ applyLabel() || ('filter.apply' | t) }}
              </app-button>
            }
            @if (live() ? activeCount() > 0 : true) {
              <app-button variant="ghost" size="sm" (click)="emitReset()">
                {{ resetLabel() || ('filter.reset' | t) }}
              </app-button>
            }
          </div>
        </div>
      }
    </div>
  `,
  styles: [
    `
      .filter {
        position: relative;
      }
      .filter__btn {
        display: inline-flex;
        align-items: center;
        gap: var(--space-2);
      }
      .filter__count {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 1.25rem;
        height: 1.25rem;
        padding: 0 var(--space-1);
        margin-left: var(--space-1);
        border-radius: 999px;
        background: var(--color-primary);
        color: var(--color-on-primary, #fff);
        font-size: var(--fs-xs);
        font-weight: var(--fw-bold);
      }
      .filter__panel {
        position: absolute;
        right: 0;
        z-index: var(--z-dropdown, 50);
        margin-top: var(--space-2);
        width: min(22rem, 90vw);
        max-height: 80vh;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: var(--space-4);
        padding: var(--space-4);
        background: var(--color-bg-elevated, var(--color-surface));
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        box-shadow: var(--shadow-lg);
      }
      .filter__fields {
        display: flex;
        flex-direction: column;
        gap: var(--space-4);
      }
      .filter__actions {
        display: flex;
        gap: var(--space-2);
      }

      /* Mobil (≤768px): Popover würde links aus dem Viewport laufen (rechts am
         Button verankert, 22rem breit) — stattdessen als Bottom-Sheet über die
         volle Breite, wie der Dialog. Desktop unverändert. */
      @media (max-width: 768px) {
        .filter__panel {
          position: fixed;
          inset: auto 0 0 0;
          margin-top: 0;
          width: auto;
          max-height: 80dvh;
          border-radius: var(--radius-lg) var(--radius-lg) 0 0;
          border-bottom: 0;
          z-index: var(--z-dialog);
        }
        .filter__actions app-button {
          flex: 1 1 auto;
          display: flex;
        }
      }
    `,
  ],
})
export class FilterBarComponent {
  private readonly host = inject(ElementRef<HTMLElement>);
  protected readonly i18n = inject(I18nService);

  /** Anzahl aktiver Filter (Badge); 0 blendet den Zähler aus. */
  readonly activeCount = input(0);
  /** Button-Label; leer = i18n-Default „Filter". */
  readonly label = input('');
  /** Live-Modus: keine „Anwenden"-Taste (Felder wirken sofort). */
  readonly live = input(false);
  readonly applyLabel = input('');
  readonly resetLabel = input('');

  /** „Anwenden" geklickt (Apply-Modus). Schließt das Popover. */
  readonly apply = output<void>();
  /** „Zurücksetzen" geklickt. */
  readonly reset = output<void>();
  /** Offen-Zustand geändert (z. B. zum Re-Fokus). */
  readonly openChange = output<boolean>();

  protected readonly open = signal(false);
  /** True, wenn das Popover geöffnet ist (für Konsumenten via Template-Ref). */
  readonly isOpen = computed(() => this.open());

  toggle(): void {
    this.setOpen(!this.open());
  }

  close(): void {
    if (this.open()) this.setOpen(false);
  }

  protected emitApply(): void {
    this.apply.emit();
    this.setOpen(false);
  }

  protected emitReset(): void {
    this.reset.emit();
  }

  private setOpen(value: boolean): void {
    this.open.set(value);
    this.openChange.emit(value);
  }

  @HostListener('document:click', ['$event'])
  protected onDocumentClick(event: MouseEvent): void {
    if (!this.open()) return;
    if (!this.host.nativeElement.contains(event.target as Node)) this.setOpen(false);
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    this.close();
  }
}
