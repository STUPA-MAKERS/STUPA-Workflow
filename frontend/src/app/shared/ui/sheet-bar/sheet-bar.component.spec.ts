import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { SheetBarComponent, SheetBarKickerDirective } from './sheet-bar.component';

@Component({
  standalone: true,
  imports: [SheetBarComponent],
  template: `
    <app-sheet-bar [kicker]="kicker()" [kickerId]="id()" [bleed]="bleed()">
      <button type="button">Edit</button>
    </app-sheet-bar>
  `,
})
class HostComponent {
  readonly kicker = signal<string | null>('Studierendenparlament · Di, 29.09.2026');
  readonly id = signal<string | null>(null);
  readonly bleed = signal(false);
}

@Component({
  standalone: true,
  imports: [SheetBarComponent, SheetBarKickerDirective],
  template: `
    <app-sheet-bar kicker="ignored">
      <nav appSheetBarKicker aria-label="Pfad"><button type="button">Haushalt</button></nav>
      <button type="button">Export</button>
    </app-sheet-bar>
  `,
})
class SlotHostComponent {}

describe('SheetBarComponent', () => {
  function render() {
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    return { fixture, el, bar: el.querySelector('app-sheet-bar') as HTMLElement };
  }

  it('shows the kicker as one line with its full text as the tooltip', () => {
    const { bar } = render();
    const k = bar.querySelector('.sheet-bar__kicker') as HTMLElement;
    expect(k.tagName).toBe('SPAN');
    expect(k.textContent?.trim()).toBe('Studierendenparlament · Di, 29.09.2026');
    expect(k.getAttribute('title')).toBe('Studierendenparlament · Di, 29.09.2026');
    expect(k.classList).toContain('ell');
    expect(bar.classList).toContain('sheet-bar');
  });

  it('projects the actions after the kicker', () => {
    const { bar } = render();
    expect(bar.lastElementChild?.tagName).toBe('BUTTON');
  });

  it('renders the kicker as a section heading when it has an id', () => {
    const { fixture, bar } = render();
    fixture.componentInstance.id.set('cal-day');
    fixture.detectChanges();
    const k = bar.querySelector('.sheet-bar__kicker') as HTMLElement;
    expect(k.tagName).toBe('H2');
    expect(k.id).toBe('cal-day');
  });

  it('keeps an empty tooltip without a kicker', () => {
    const { fixture, bar } = render();
    fixture.componentInstance.kicker.set(null);
    fixture.componentInstance.id.set('x');
    fixture.detectChanges();
    expect(bar.querySelector('.sheet-bar__kicker')?.getAttribute('title')).toBe('');
    fixture.componentInstance.id.set(null);
    fixture.detectChanges();
    expect(bar.querySelector('.sheet-bar__kicker')?.getAttribute('title')).toBe('');
  });

  it('reaches into the sheet padding only with bleed', () => {
    const { fixture, bar } = render();
    expect(bar.classList).not.toContain('sheet-bar--bleed');
    fixture.componentInstance.bleed.set(true);
    fixture.detectChanges();
    expect(bar.classList).toContain('sheet-bar--bleed');
  });

  it('puts a projected kicker in the place of the text kicker', () => {
    const fixture = TestBed.createComponent(SlotHostComponent);
    fixture.detectChanges();
    const bar = (fixture.nativeElement as HTMLElement).querySelector('app-sheet-bar') as HTMLElement;
    const kickers = bar.querySelectorAll('.sheet-bar__kicker');
    expect(kickers).toHaveLength(1);
    const k = kickers[0] as HTMLElement;
    expect(k).toHaveClass('sheet-bar__kicker--slot');
    expect(k.firstElementChild?.tagName).toBe('NAV');
    expect(bar.textContent).not.toContain('ignored');
    // The kicker comes first, the actions after it.
    expect(bar.firstElementChild).toBe(k);
    expect(bar.lastElementChild?.textContent).toBe('Export');
  });
});
