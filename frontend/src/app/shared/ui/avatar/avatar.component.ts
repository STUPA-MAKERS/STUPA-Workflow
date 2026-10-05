import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { AvatarService } from './avatar.service';

/** The size of an avatar: 40px (`md`) or 32px (`sm`). */
export type AvatarSize = 'md' | 'sm';

/**
 * The initials of a name: the first letter of the first and of the last word.
 *
 * "Mara Keller" gives "MK", "Paul" gives "P", "Anna-Lena von Stein" gives "AS". Words in
 * brackets (an e-mail or a note) do not count.
 */
export function initials(name: string): string {
  const words = name
    .replace(/\(.*?\)/g, ' ')
    .split(/\s+/)
    .map((w) => w.replace(/^[^\p{L}\p{N}]+/u, ''))
    .filter((w) => w.length > 0);
  if (words.length === 0) return '?';
  const first = [...words[0]][0];
  const last = words.length > 1 ? [...words[words.length - 1]][0] : '';
  return (first + last).toLocaleUpperCase();
}

/** The edge length of an avatar in CSS pixels, per size. */
const AVATAR_PX: Record<AvatarSize, number> = { md: 40, sm: 32 };

/**
 * The initials of a PERSON in a circle, or the Gravatar image of the person.
 *
 * Only for persons: members, keepers, delegations. Never put initials on a row of a thing
 * (an application, an invoice); give that row an icon or nothing.
 *
 * With `principalId` (a principal id, or `'me'` for the logged-in user) the avatar loads
 * the image through the API proxy (`AvatarService`). The initials stay below the image
 * until it has loaded, and come back when it fails (no Gravatar, the proxy is off): the
 * circle keeps its size, so nothing moves.
 *
 * The full name is the accessible name and the tooltip. Set `decorative` when the name
 * is already written next to the avatar, so a screen reader does not read it twice.
 */
@Component({
  selector: 'app-avatar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '[class.av--sm]': "size() === 'sm'",
    '[class.av--accent]': 'accent()',
    '[class.av--img]': 'loaded()',
    '[attr.role]': "decorative() ? null : 'img'",
    '[attr.aria-label]': 'decorative() ? null : name()',
    '[attr.aria-hidden]': "decorative() ? 'true' : null",
    '[attr.title]': 'name()',
  },
  templateUrl: './avatar.component.html',
  styleUrl: './avatar.component.scss',
})
export class AvatarComponent {
  /** The full name of the person. */
  readonly name = input.required<string>();
  readonly size = input<AvatarSize>('md');
  /** Fill with the accent, for the viewer's own avatar. */
  readonly accent = input(false);
  /** The name is written next to the avatar: hide the avatar from screen readers. */
  readonly decorative = input(false);
  /** The principal id of the person, or `'me'`. Without it the avatar shows the initials. */
  readonly principalId = input<string | null | undefined>(null);

  private readonly avatars = inject(AvatarService);

  protected readonly letters = computed(() => initials(this.name()));

  /** The image URL, or `null` for the initials only. */
  protected readonly src = computed(() =>
    this.avatars.url(this.principalId(), AVATAR_PX[this.size()]),
  );

  /** The URL of the image that has loaded. A new URL starts hidden again. */
  private readonly loadedSrc = signal<string | null>(null);
  protected readonly loaded = computed(() => {
    const src = this.src();
    return src !== null && this.loadedSrc() === src;
  });

  protected onLoad(): void {
    this.loadedSrc.set(this.src());
  }

  protected onError(): void {
    const id = this.principalId();
    if (id) this.avatars.markFailed(id);
  }
}

/**
 * Overlapping avatars of a group of persons, with a "+N" for the rest.
 *
 * The group is one image for a screen reader: its name lists the shown persons and the
 * number of the others.
 */
@Component({
  selector: 'app-avatar-stack',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [AvatarComponent],
  host: {
    role: 'img',
    '[attr.aria-label]': 'label()',
    '[attr.title]': 'label()',
  },
  templateUrl: './avatar-stack.component.html',
  styleUrl: './avatar-stack.component.scss',
})
export class AvatarStackComponent {
  private readonly i18n = inject(I18nService);

  /** The full names of the persons. */
  readonly names = input.required<readonly string[]>();
  /** How many avatars to draw before the "+N". */
  readonly max = input(4);
  readonly size = input<AvatarSize>('sm');

  protected readonly shown = computed(() => this.names().slice(0, Math.max(1, this.max())));
  protected readonly rest = computed(() => this.names().length - this.shown().length);

  protected readonly label = computed(() => {
    const shown = this.shown().join(', ');
    const rest = this.rest();
    if (rest === 0) return shown;
    return `${shown}, ${this.i18n.translate('ui.avatarStack.more', { count: rest })}`;
  });
}
