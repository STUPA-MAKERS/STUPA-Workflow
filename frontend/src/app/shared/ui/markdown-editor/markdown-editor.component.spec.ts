import { Component, signal } from '@angular/core';
import { render } from '@testing-library/angular';
import { MarkdownEditorComponent } from './markdown-editor.component';

@Component({
  standalone: true,
  imports: [MarkdownEditorComponent],
  template: `<app-markdown-editor
    [value]="value()"
    [docKey]="docKey()"
    [disabled]="disabled()"
    [placeholder]="placeholder()"
    (valueChange)="onChange($event)"
  />`,
})
class Host {
  readonly value = signal('');
  readonly docKey = signal('');
  readonly disabled = signal(false);
  readonly placeholder = signal('');
  readonly changes: string[] = [];
  onChange(v: string): void {
    this.changes.push(v);
  }
}

function editorEl(container: HTMLElement): HTMLElement {
  // Tiptap mounts a contenteditable ProseMirror node inside the host div.
  return container.querySelector('.ProseMirror') as HTMLElement;
}

describe('MarkdownEditorComponent', () => {
  it('builds a Tiptap editor mounted in the host element with initial value', async () => {
    const { container } = await render(Host, {
      componentProperties: {} as Partial<Host>,
    });
    const pm = editorEl(container);
    expect(pm).toBeTruthy();
    expect(pm.getAttribute('contenteditable')).toBe('true');
  });

  it('renders the provided initial markdown content', async () => {
    const { container } = await render(`<app-markdown-editor [value]="'# Titel'" />`, {
      imports: [MarkdownEditorComponent],
    });
    const pm = editorEl(container);
    expect(pm.textContent).toContain('Titel');
  });

  it('disables editing when [disabled] is true (initial)', async () => {
    const { container } = await render(`<app-markdown-editor [disabled]="true" />`, {
      imports: [MarkdownEditorComponent],
    });
    const pm = editorEl(container);
    expect(pm.getAttribute('contenteditable')).toBe('false');
  });

  it('toggles editability reactively via setEditable', async () => {
    const view = await render(Host);
    const pm = editorEl(view.container);
    expect(pm.getAttribute('contenteditable')).toBe('true');

    view.fixture.componentInstance.disabled.set(true);
    view.fixture.detectChanges();
    await view.fixture.whenStable();
    expect(pm.getAttribute('contenteditable')).toBe('false');

    view.fixture.componentInstance.disabled.set(false);
    view.fixture.detectChanges();
    await view.fixture.whenStable();
    expect(pm.getAttribute('contenteditable')).toBe('true');
  });

  it('passes the placeholder to the editor element attributes', async () => {
    const { container } = await render(`<app-markdown-editor [placeholder]="'Schreib was…'" />`, {
      imports: [MarkdownEditorComponent],
    });
    const pm = editorEl(container);
    expect(pm.getAttribute('data-placeholder')).toBe('Schreib was…');
  });

  it('emits serialized markdown on user edits (onUpdate)', async () => {
    const view = await render(Host);
    const host = view.fixture.componentInstance;
    const cmp = view.fixture.debugElement.children[0]
      .componentInstance as MarkdownEditorComponent;
    // Drive the editor imperatively → triggers onUpdate → valueChange.
    const editor = (cmp as unknown as { editor: { commands: { setContent: (c: string) => void; insertContent: (c: string) => void } } })
      .editor;
    editor.commands.insertContent('Neuer Text');
    view.fixture.detectChanges();
    expect(host.changes.length).toBeGreaterThan(0);
    expect(host.changes.at(-1)).toContain('Neuer Text');
  });

  it('reloads content (without emitting) when docKey changes', async () => {
    const view = await render(Host);
    const host = view.fixture.componentInstance;
    host.value.set('Geladener Inhalt');
    host.docKey.set('doc-2');
    view.fixture.detectChanges();
    await view.fixture.whenStable();
    const pm = editorEl(view.container);
    expect(pm.textContent).toContain('Geladener Inhalt');
    // The synchronous `emitting` guard suppresses a valueChange that would
    // otherwise echo the freshly loaded document text back to the consumer.
    expect(host.changes).not.toContain('Geladener Inhalt');
  });

  it('does not reload content when docKey is unchanged but value changes', async () => {
    const view = await render(Host);
    const host = view.fixture.componentInstance;
    // No docKey change → editor keeps current (empty) content.
    host.value.set('Ignoriert weil docKey gleich');
    view.fixture.detectChanges();
    await view.fixture.whenStable();
    const pm = editorEl(view.container);
    expect(pm.textContent).not.toContain('Ignoriert');
  });

  it('destroys the editor on component teardown', async () => {
    const view = await render(Host);
    const cmp = view.fixture.debugElement.children[0]
      .componentInstance as MarkdownEditorComponent;
    const editor = (cmp as unknown as { editor: { isDestroyed: boolean } }).editor;
    view.fixture.destroy();
    expect(editor.isDestroyed).toBe(true);
    expect((cmp as unknown as { editor: unknown }).editor).toBeNull();
  });

  it('toMarkdown returns empty string when the markdown storage is absent', async () => {
    const view = await render(Host);
    const cmp = view.fixture.debugElement.children[0]
      .componentInstance as MarkdownEditorComponent;
    const fakeEditor = { storage: {} } as unknown as Parameters<
      (typeof cmp)['toMarkdown' & keyof typeof cmp]
    >[0];
    const md = (
      cmp as unknown as { toMarkdown: (e: unknown) => string }
    ).toMarkdown(fakeEditor);
    expect(md).toBe('');
  });

  it('toMarkdown reads getMarkdown from the storage when present', async () => {
    const view = await render(Host);
    const cmp = view.fixture.debugElement.children[0]
      .componentInstance as MarkdownEditorComponent;
    const fakeEditor = {
      storage: { markdown: { getMarkdown: () => '**bold**' } },
    };
    const md = (
      cmp as unknown as { toMarkdown: (e: unknown) => string }
    ).toMarkdown(fakeEditor);
    expect(md).toBe('**bold**');
  });
});
