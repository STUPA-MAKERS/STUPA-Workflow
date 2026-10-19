import { Component, signal } from '@angular/core';
import { fireEvent, render } from '@testing-library/angular';
import { FileDropDirective, isFileDrag } from './file-drop.directive';

@Component({
  standalone: true,
  imports: [FileDropDirective],
  template: `
    <div id="page" (drop)="pageDrops = pageDrops + 1">
      <div
        id="zone"
        appFileDrop
        #zone="appFileDrop"
        [appFileDropEnabled]="enabled()"
        (appFileDrop)="dropped.push($event)"
      >
        <span id="child">{{ zone.active() ? 'aktiv' : 'ruhig' }}</span>
      </div>
    </div>
  `,
})
class HostComponent {
  readonly enabled = signal(true);
  readonly dropped: File[][] = [];
  pageDrops = 0;
}

const files = { types: ['Files'] };
const pdf = new File(['x'], 'a.pdf', { type: 'application/pdf' });

async function setup() {
  const view = await render(HostComponent);
  const zone = view.container.querySelector('#zone') as HTMLElement;
  const child = view.container.querySelector('#child') as HTMLElement;
  const state = () => {
    view.fixture.detectChanges();
    return child.textContent;
  };
  return { view, zone, child, state, host: view.fixture.componentInstance };
}

describe('isFileDrag', () => {
  it('is true only for a drag that carries files', () => {
    expect(isFileDrag({ dataTransfer: { types: ['Files'] } } as unknown as DragEvent)).toBe(true);
    expect(isFileDrag({ dataTransfer: { types: ['text/plain'] } } as unknown as DragEvent)).toBe(false);
    expect(isFileDrag({ dataTransfer: null } as unknown as DragEvent)).toBe(false);
  });
});

describe('FileDropDirective', () => {
  it('is active from the first enter to the last leave, over the children too', async () => {
    const { zone, child, state } = await setup();
    expect(fireEvent.dragEnter(zone, { dataTransfer: files })).toBe(false);
    fireEvent.dragEnter(child, { dataTransfer: files });
    fireEvent.dragLeave(zone, { dataTransfer: files });
    expect(state()).toBe('aktiv');
    fireEvent.dragLeave(child, { dataTransfer: files });
    expect(state()).toBe('ruhig');
    fireEvent.dragLeave(zone, { dataTransfer: files });
    expect(state()).toBe('ruhig');
  });

  it('allows the drop with a copy effect', async () => {
    const { zone } = await setup();
    const dataTransfer = { types: ['Files'], dropEffect: 'none' };
    expect(fireEvent.dragOver(zone, { dataTransfer })).toBe(false);
    expect(dataTransfer.dropEffect).toBe('copy');
  });

  it('emits the dropped files once and keeps the drop from the page', async () => {
    const { zone, state, host } = await setup();
    fireEvent.dragEnter(zone, { dataTransfer: files });
    expect(fireEvent.drop(zone, { dataTransfer: { types: ['Files'], files: [pdf] } })).toBe(false);
    expect(host.dropped).toEqual([[pdf]]);
    expect(host.pageDrops).toBe(0);
    expect(state()).toBe('ruhig');
  });

  it('emits nothing for a drop without files', async () => {
    const { zone, host } = await setup();
    fireEvent.drop(zone, { dataTransfer: { types: ['Files'], files: [] } });
    expect(host.dropped).toEqual([]);
  });

  it('leaves a text drag alone', async () => {
    const { zone, state, host } = await setup();
    const text = { types: ['text/plain'] };
    expect(fireEvent.dragEnter(zone, { dataTransfer: text })).toBe(true);
    expect(fireEvent.dragOver(zone)).toBe(true);
    expect(fireEvent.dragLeave(zone, { dataTransfer: text })).toBe(true);
    expect(state()).toBe('ruhig');
    fireEvent.drop(zone, { dataTransfer: text });
    expect(host.pageDrops).toBe(1);
  });

  it('lets a file drag pass to the page while it is off', async () => {
    const { view, zone, state, host } = await setup();
    host.enabled.set(false);
    view.fixture.detectChanges();
    expect(fireEvent.dragEnter(zone, { dataTransfer: files })).toBe(true);
    expect(state()).toBe('ruhig');
    fireEvent.drop(zone, { dataTransfer: { types: ['Files'], files: [pdf] } });
    expect(host.dropped).toEqual([]);
    expect(host.pageDrops).toBe(1);
  });

  it('hides when it is turned off during a drag', async () => {
    const { zone, state, host } = await setup();
    fireEvent.dragEnter(zone, { dataTransfer: files });
    expect(state()).toBe('aktiv');
    host.enabled.set(false);
    expect(state()).toBe('ruhig');
    host.enabled.set(true);
    fireEvent.dragEnter(zone, { dataTransfer: files });
    fireEvent.dragLeave(zone, { dataTransfer: files });
    expect(state()).toBe('ruhig');
  });
});
