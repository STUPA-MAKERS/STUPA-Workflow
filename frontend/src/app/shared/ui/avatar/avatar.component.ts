import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';

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

/**
 * The initials of a PERSON in a circle.
 *
 * Only for persons: members, keepers, delegations. Never put initials on a row of a thing
 * (an application, an invoice); give that row an icon or nothing.
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

  protected readonly letters = computed(() => initials(this.name()));
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
