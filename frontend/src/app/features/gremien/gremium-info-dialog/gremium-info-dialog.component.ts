import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { GremienApiService, type GremiumInfo, type GremiumInfoLink } from '@core/api/gremien.service';
import { problemCode } from '@core/api/problem';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { MarkdownImageUploadDirective } from '@shared/markdown/markdown-image-upload.directive';
import { MarkdownViewComponent } from '@shared/markdown/markdown-view.component';
import {
  ButtonComponent,
  ButtonGroupComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  MoveButtonsComponent,
  moveItem,
  SegmentedComponent,
  type SegmentedOption,
  TextareaComponent,
  ToastService,
  ErrorTextComponent,
  DialogBodyDirective,
} from '@stupa-makers/ui-kit';
import { INFO_MAX_LABEL, INFO_MAX_LINKS, INFO_MAX_TEXT, infoUrlValid } from '../gremien.util';

/** One row of the link editor; `key` keeps the row identity while rows move. */
export interface InfoLinkDraft {
  readonly key: number;
  readonly label: string;
  readonly url: string;
}

/** The error of one link row, or `null`; an empty row is no error, the save drops it. */
export interface InfoLinkErrors {
  readonly label: TranslationKey | null;
  readonly url: TranslationKey | null;
}

type InfoMode = 'write' | 'preview';

const CONFLICT = 'gremium_info_version_conflict';

/** The row is blank: no label and no URL. The save leaves it out. */
export function linkBlank(link: InfoLinkDraft): boolean {
  return link.label.trim() === '' && link.url.trim() === '';
}

/** The errors of one row of the link editor (spec 001012). */
export function linkErrors(link: InfoLinkDraft): InfoLinkErrors {
  const blank = linkBlank(link);
  const label = link.label.trim();
  return {
    label:
      blank || (label !== '' && label.length <= INFO_MAX_LABEL)
        ? null
        : label === ''
          ? 'gremien.info.labelRequired'
          : 'gremien.info.labelTooLong',
    url: blank || infoUrlValid(link.url) ? null : 'gremien.info.urlInvalid',
  };
}

/** The links of the drafts, in their order, without blank rows and trimmed. */
export function draftLinks(drafts: readonly InfoLinkDraft[]): readonly GremiumInfoLink[] {
  return drafts
    .filter((d) => !linkBlank(d))
    .map((d) => ({ label: d.label.trim(), url: d.url.trim() }));
}

/**
 * The editor of the Info tab (specs 001011-001014): the Markdown text with "Schreiben"
 * and "Vorschau", and the labelled links in their order with up, down and remove.
 *
 * Text and links save together with the version that the tab read. A stale version gives
 * 409: the dialog says so and keeps the draft, and the tab loads the newer Info
 * (`stale`). The server stays authoritative for `info.write`.
 */
@Component({
  selector: 'app-gremium-info-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DialogBodyDirective,
    ErrorTextComponent,
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    ButtonGroupComponent,
    DialogComponent,
    IconComponent,
    InputComponent,
    MoveButtonsComponent,
    SegmentedComponent,
    TextareaComponent,
    MarkdownImageUploadDirective,
    MarkdownViewComponent,
  ],
  templateUrl: './gremium-info-dialog.component.html',
  styleUrl: './gremium-info-dialog.component.scss',
})
export class GremiumInfoDialogComponent {
  private readonly api = inject(GremienApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = input(false);
  readonly gremiumId = input.required<string>();
  readonly gremiumName = input('');
  readonly info = input.required<GremiumInfo>();
  readonly closed = output<void>();
  readonly saved = output<GremiumInfo>();
  /** The save met a newer Info (409): the tab loads it again. */
  readonly stale = output<void>();

  readonly maxText = INFO_MAX_TEXT;
  readonly maxLabel = INFO_MAX_LABEL;
  readonly body = signal('');
  readonly links = signal<readonly InfoLinkDraft[]>([]);
  readonly mode = signal<InfoMode>('write');
  readonly saving = signal(false);
  /** The person pressed "Speichern" once: the row errors show from now on. */
  readonly tried = signal(false);
  readonly conflict = signal(false);
  private nextKey = 0;

  readonly modeOptions = computed<readonly SegmentedOption[]>(() => [
    { value: 'write', label: this.i18n.translate('gremien.info.write') },
    { value: 'preview', label: this.i18n.translate('gremien.info.preview') },
  ]);
  readonly errors = computed(() => this.links().map(linkErrors));
  readonly valid = computed(() => this.errors().every((e) => e.label === null && e.url === null));
  readonly full = computed(() => this.links().length >= INFO_MAX_LINKS);

  constructor() {
    effect(() => {
      if (!this.open()) return;
      const info = this.info();
      untracked(() => this.reset(info));
    });
  }

  private reset(info: GremiumInfo): void {
    this.body.set(info.bodyMd);
    this.links.set(info.links.map((l) => this.draft(l.label, l.url)));
    this.mode.set('write');
    this.tried.set(false);
    this.conflict.set(false);
  }

  private draft(label: string, url: string): InfoLinkDraft {
    this.nextKey += 1;
    return { key: this.nextKey, label, url };
  }

  setMode(value: string | null): void {
    this.mode.set(value === 'preview' ? 'preview' : 'write');
  }

  addLink(): void {
    if (this.full()) return;
    this.links.update((rows) => [...rows, this.draft('', '')]);
  }

  removeLink(key: number): void {
    this.links.update((rows) => rows.filter((r) => r.key !== key));
  }

  moveLink(index: number, dir: -1 | 1): void {
    this.links.update((rows) => moveItem(rows, index, dir));
  }

  setLabel(key: number, label: string): void {
    this.links.update((rows) => rows.map((r) => (r.key === key ? { ...r, label } : r)));
  }

  setUrl(key: number, url: string): void {
    this.links.update((rows) => rows.map((r) => (r.key === key ? { ...r, url } : r)));
  }

  error(key: TranslationKey | null): string {
    return this.tried() && key !== null ? this.i18n.translate(key) : '';
  }

  cancel(): void {
    this.closed.emit();
  }

  save(): void {
    this.tried.set(true);
    if (!this.valid() || this.saving()) return;
    this.saving.set(true);
    this.conflict.set(false);
    const body = { bodyMd: this.body(), links: draftLinks(this.links()), version: this.info().version };
    this.api.saveInfo(this.gremiumId(), body).subscribe({
      next: (info) => {
        this.saving.set(false);
        this.toast.show({ text: this.i18n.translate('gremien.info.saved'), kind: 'success' });
        this.saved.emit(info);
        this.closed.emit();
      },
      error: (err: unknown) => {
        this.saving.set(false);
        if (problemCode(err) === CONFLICT) {
          this.conflict.set(true);
          this.stale.emit();
          return;
        }
        this.toast.show({ text: this.i18n.translate('gremien.info.saveError'), kind: 'error' });
      },
    });
  }
}
