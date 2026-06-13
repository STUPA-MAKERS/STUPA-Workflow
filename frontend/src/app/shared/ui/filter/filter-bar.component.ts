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
  templateUrl: './filter-bar.component.html',
  styleUrl: './filter-bar.component.scss',
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
