import { Injectable, Injector, inject, type OnDestroy } from '@angular/core';
import { DRAFT_FILES_PERSIST, DraftAttachmentsService } from '../../../features/apply/draft-attachments.service';

/**
 * The composer files of a page whose layout switch re-creates `app-chat` (the ticket and
 * the application detail render the thread in one branch for two panes and in another
 * for tabs). The page provides this service, so the uploaded drafts belong to the page:
 * a new chat takes them over with the text draft, and they go when the page goes.
 *
 * One chat holds the drafts at a time. A second chat on the same page while the first
 * still lives gets drafts of its own, so two threads never share their files.
 */
@Injectable()
export class ChatDrafts implements OnDestroy {
  private readonly drafts = Injector.create({
    providers: [{ provide: DRAFT_FILES_PERSIST, useValue: false }, DraftAttachmentsService],
    parent: inject(Injector),
  }).get(DraftAttachmentsService);
  private held = false;
  /** The thread whose files the drafts hold, or null before the first chat. */
  key: string | null = null;

  /** The drafts for a new chat, or null while another chat holds them. */
  claim(): DraftAttachmentsService | null {
    if (this.held) return null;
    this.held = true;
    return this.drafts;
  }

  /** The chat that held the drafts is gone; the files stay for the next one. */
  release(): void {
    this.held = false;
  }

  /** Is this the page's drafts service. */
  holds(drafts: DraftAttachmentsService): boolean {
    return drafts === this.drafts;
  }

  ngOnDestroy(): void {
    void this.drafts.discard();
  }
}
