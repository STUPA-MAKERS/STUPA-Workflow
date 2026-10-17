import { type ComponentFixture, DeferBlockState } from '@angular/core/testing';

/**
 * Render every `@defer` block of a fixture in its loaded state.
 *
 * A heavy child (the Markdown editor with Tiptap and KaTeX) sits in a `@defer` block, so
 * its code is a lazy chunk of its own. A spec that reads the child calls this first, and
 * again after a change that draws a new block.
 */
export async function renderDeferred(fixture: ComponentFixture<unknown>): Promise<void> {
  for (const block of await fixture.getDeferBlocks()) {
    await block.render(DeferBlockState.Complete);
  }
  fixture.detectChanges();
}
