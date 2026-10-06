import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  CurrencyInputComponent,
  DatepickerComponent,
  DialogComponent,
  InputComponent,
} from '@stupa-makers/ui-kit';
import type { ExpenseSubBookingsState } from '../expense-sub-bookings.state';

/**
 * Add a sub-booking to a booking. The sub-booking takes the cost centre, the fiscal year
 * and the kind of its parent; the parent amount becomes the sum of its sub-bookings.
 */
@Component({
  selector: 'app-sub-booking-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ButtonComponent,
    CurrencyInputComponent,
    DatepickerComponent,
    DialogComponent,
    FormsModule,
    InputComponent,
    TranslatePipe,
  ],
  templateUrl: './sub-booking-dialog.component.html',
  styleUrl: './sub-booking-dialog.component.scss',
})
export class SubBookingDialogComponent {
  readonly sub = input.required<ExpenseSubBookingsState>();
  readonly saving = input(false);
}
