import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import { API_BASE_URL } from '@core/api/api.config';
import type { ApplicationComment, Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { actorLabel } from '@shared/actor-label.util';
import {
  ChatComponent,
  ChatOutbox,
  appendOnce,
  chatPeople,
  draftDropper,
  sendErrorKey,
  toChatAttachments,
  withScanStates,
  type ChatEdit,
  type ChatMessage,
  type ChatPerson,
  type ChatRef,
  type ChatSend,
  type ChatVisibility,
  type ChatVisibilityGuard,
} from '@shared/ui';
import { withoutKey } from '@shared/util/immutable';
import { ToastService } from '@stupa-makers/ui-kit';

const VISIBILITY_GUARD: ChatVisibilityGuard = {
  labels: { internal: 'applications.comments.vis.internal', public: 'applications.comments.vis.public' },
};

/**
 * The comments of the Antrag of a Bestellung, in the detail of the Bestellung.
 *
 * A Bestellung has no comments of its own, because the people talk about a purchase
 * where they talk about the Antrag. A comment written here is a comment of the Antrag:
 * the read, the write and the visibility follow the rules of the Antrag, so the switch
 * to an internal comment shows only with `application.manage`.
 */
@Component({
  selector: 'app-order-comments',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ChatComponent],
  template: `
    <app-chat
      [loading]="loading()"
      [draftKey]="'application.' + applicationId()"
      [messages]="messages()"
      [visibilityOptions]="visibilities()"
      [visibilityGuard]="guard"
      [canAttach]="true"
      [mentionables]="mentionables()"
      [publicMentions]="false"
      placeholder="applications.comments.placeholder"
      (send)="send($event)"
      (retry)="outbox.retry($event.id)"
      (discard)="outbox.discard($event.id)"
      (edit)="edit($event)"
      (delete)="remove($event)"
      (refresh)="refresh()"
    />
  `,
})
export class OrderCommentsComponent {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly apiBase = inject(API_BASE_URL);

  readonly applicationId = input.required<Uuid>();

  protected readonly guard = VISIBILITY_GUARD;
  protected readonly loading = signal(true);
  protected readonly mentionables = signal<readonly ChatPerson[]>([]);
  private readonly comments = signal<readonly ApplicationComment[]>([]);
  private readonly canManage = computed(() => this.auth.can('application.manage'));

  protected readonly visibilities = computed<readonly ChatVisibility[]>(() =>
    this.canManage() ? ['internal', 'public'] : [],
  );

  protected readonly outbox = new ChatOutbox<ApplicationComment>(
    (req) =>
      this.api.addComment(this.applicationId(), req.body, req.visibility ?? 'public', req, req.mentions),
    (created) => this.comments.update((list) => appendOnce(list, created)),
    (err) => this.toast.show(this.i18n.translate(sendErrorKey(err, 'applications.comments.error')), 'error'),
    draftDropper(this.api),
  );

  protected readonly messages = computed<readonly ChatMessage[]>(() => [
    ...this.comments().map((c) => this.message(c)),
    ...this.outbox.messages(),
  ]);

  constructor() {
    effect(() => {
      const id = this.applicationId();
      this.loading.set(true);
      this.comments.set([]);
      this.api.comments(id, { quiet: true }).subscribe({
        next: (list) => {
          if (id !== this.applicationId()) return;
          this.comments.set(list);
          this.loading.set(false);
        },
        error: () => this.loading.set(false),
      });
      this.api.mentionable(id).subscribe({
        next: (people) => this.mentionables.set(chatPeople(people)),
        error: () => this.mentionables.set([]),
      });
    });
  }

  /** Without `application.manage` the composer has no switch, so the comment is public. */
  protected send(req: ChatSend): void {
    this.outbox.send(this.canManage() ? { ...req } : withoutKey(req, 'visibility'));
  }

  protected edit(change: ChatEdit): void {
    this.api.updateComment(this.applicationId(), change.id, change.body, change.mentions).subscribe({
      next: (updated) =>
        this.comments.update((list) => list.map((c) => (c.id === updated.id ? updated : c))),
      error: () => {
        change.restore?.();
        this.toast.show(this.i18n.translate('applications.comments.error'), 'error');
      },
    });
  }

  protected remove(ref: ChatRef): void {
    this.api.deleteComment(this.applicationId(), ref.id).subscribe({
      next: () => this.comments.update((list) => list.filter((c) => c.id !== ref.id)),
      error: () => this.toast.show(this.i18n.translate('applications.comments.error'), 'error'),
    });
  }

  /** Read again for the scan states of the files; a failure keeps the thread. */
  protected refresh(): void {
    this.api.comments(this.applicationId(), { quiet: true }).subscribe({
      next: (fresh) => this.comments.update((list) => withScanStates(list, fresh)),
      error: () => undefined,
    });
  }

  private message(comment: ApplicationComment): ChatMessage {
    const info =
      comment.authorInfo ?? (comment.authorKind === 'applicant' ? { kind: 'applicant' as const } : null);
    const name =
      actorLabel(info, comment.author, (key, params) => this.i18n.translate(key, params), {
        applicantName: null,
      }) ?? this.i18n.translate('applications.comments.author.committee');
    return {
      id: comment.id,
      author: { principalId: comment.authorInfo?.principalId ?? null, displayName: name },
      body: comment.body,
      at: comment.at,
      editedAt: comment.editedAt,
      own: comment.isOwn,
      canEdit: comment.isOwn || this.canManage(),
      visibility: comment.visibility,
      attachments: toChatAttachments(this.apiBase, comment.attachments),
      mentions: comment.mentions,
    };
  }
}
