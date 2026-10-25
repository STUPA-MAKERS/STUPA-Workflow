import { ChangeDetectionStrategy, Component, computed, inject, input, model, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { PollMode } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  DatepickerComponent,
  IconComponent,
  InputComponent,
  MoveButtonsComponent,
  moveItem,
  SegmentedComponent,
  type SegmentedOption,
  TimeInputComponent,
  TruncatedDirective,
} from '@stupa-makers/ui-kit';
import {
  POLL_LABEL_MAX,
  POLL_MAX_OPTIONS,
  type PollDraft,
  type PollOptionDraft,
  draftDateLabel,
  draftOptions,
} from '../poll.util';

const MODES: readonly PollMode[] = ['single', 'multi', 'date'];

/**
 * The options of a poll ("Umfrage"), for the vote dialog of a meeting and the dialog
 * "Neue Umfrage": the mode ("Einzelwahl | Mehrfachwahl | Terminumfrage"), the stepper
 * "Höchstens wählbar" of a multi poll, and the option list of the candidate list of an
 * election (numbered rows, up, down, delete). A text option takes "Neue Option" and
 * "Hinzufügen"; a date poll takes Datum, Beginn and Ende and lists "Termine".
 *
 * Each mode keeps its own options: the text options and the dates stay apart, so a
 * switch of the mode loses nothing. The parent holds the draft (`draft`) and builds
 * the body with `pollInOf`.
 */
@Component({
  selector: 'app-poll-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ButtonComponent,
    DatepickerComponent,
    FormsModule,
    IconComponent,
    InputComponent,
    MoveButtonsComponent,
    SegmentedComponent,
    TimeInputComponent,
    TranslatePipe,
    TruncatedDirective,
  ],
  templateUrl: './poll-editor.component.html',
  styleUrl: './poll-editor.component.scss',
})
export class PollEditorComponent {
  private readonly i18n = inject(I18nService);

  readonly draft = model.required<PollDraft>();
  /** A prefix for the ids of the fields, unique per dialog. */
  readonly idPrefix = input('poll');

  /** The new text option. */
  readonly newLabel = signal('');
  /** The new date: `YYYY-MM-DD`, `HH:MM`, `HH:MM`. */
  readonly newDate = signal('');
  readonly newStart = signal('');
  readonly newEnd = signal('');
  private nextKey = 1;

  readonly modeOptions = computed<SegmentedOption[]>(() =>
    MODES.map((v) => ({ value: v, label: this.i18n.translate(`poll.mode.${v}`) })),
  );
  readonly mode = computed(() => this.draft().mode);
  readonly isDate = computed(() => this.mode() === 'date');
  /** The options of the current mode. */
  readonly options = computed(() => draftOptions(this.draft()));
  readonly full = computed(() => this.options().length >= POLL_MAX_OPTIONS);
  /** The stepper of a multi poll: 1 to the number of options (at least 1). */
  readonly maxLimit = computed(() => Math.max(1, this.options().length));
  readonly maxChoices = computed(() => Math.min(this.draft().maxChoices, this.maxLimit()));

  /** The typed label is on the list already (case and spacing ignored). */
  readonly labelTaken = computed(() => {
    const label = sameLabel(this.newLabel());
    return !!label && this.options().some((o) => sameLabel(o.label) === label);
  });
  /** The end lies before the start. */
  readonly endBeforeStart = computed(
    () => !!this.newEnd() && !!this.newStart() && this.newEnd() <= this.newStart(),
  );
  readonly canAddLabel = computed(
    () => !!this.newLabel().trim() && !this.labelTaken() && !this.full(),
  );
  readonly canAddDate = computed(
    () => !!this.newDate() && !!this.newStart() && !this.endBeforeStart() && !this.full(),
  );

  setMode(value: string | null): void {
    if (value !== 'single' && value !== 'multi' && value !== 'date') return;
    this.draft.update((d) => ({ ...d, mode: value }));
  }

  changeMax(delta: number): void {
    const next = Math.min(this.maxLimit(), Math.max(1, this.maxChoices() + delta));
    this.draft.update((d) => ({ ...d, maxChoices: next }));
  }

  addLabel(): void {
    if (!this.canAddLabel()) return;
    const label = this.newLabel().trim().slice(0, POLL_LABEL_MAX);
    this.append({ key: this.nextKey++, label, date: '', start: '', end: '' });
    this.newLabel.set('');
  }

  addDate(): void {
    if (!this.canAddDate()) return;
    this.append({
      key: this.nextKey++,
      label: '',
      date: this.newDate(),
      start: this.newStart(),
      end: this.newEnd(),
    });
    this.newDate.set('');
  }

  move(index: number, delta: -1 | 1): void {
    const list = this.options();
    const to = index + delta;
    if (to < 0 || to >= list.length) return;
    this.replace(moveItem(list, index, delta));
  }

  remove(key: number): void {
    this.replace(this.options().filter((o) => o.key !== key));
  }

  /** The shown text of an option. */
  label(o: PollOptionDraft): string {
    return this.isDate() ? draftDateLabel(o, this.i18n.formatLocale()) : o.label;
  }

  private append(option: PollOptionDraft): void {
    this.replace([...this.options(), option]);
  }

  /** Replace the options of the current mode; the other mode keeps its options. */
  private replace(list: PollOptionDraft[]): void {
    this.draft.update((d) => {
      const others = d.options.filter((o) => !draftOptions({ ...d, options: [o] }).length);
      return { ...d, options: [...others, ...list] };
    });
  }
}

/** A label for the duplicate check: trimmed, single spaces, case-folded. */
function sameLabel(label: string): string {
  return label.trim().replace(/\s+/g, ' ').toLowerCase();
}
