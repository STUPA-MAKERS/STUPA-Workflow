import { Directive, ElementRef, type OnDestroy, afterNextRender, inject } from '@angular/core';

/**
 * Spiegelt eine zweite, horizontale Scrollleiste **über** einem überlaufenden Container
 * (typisch eine breite Tabelle in `.exp__tableWrap`), sodass die rechten Spalten erreichbar
 * sind, ohne bis zum unteren Rand scrollen zu müssen (#expenses-ux).
 *
 * Rein DOM — keine Template-Änderung außer dem Attribut am Wrapper. Der Proxy wird als
 * Geschwister-Element direkt vor den Wrapper gesetzt; sein `scrollLeft` ist beidseitig mit
 * dem Wrapper synchronisiert. Sichtbar nur, wenn der Inhalt tatsächlich überläuft (Desktop);
 * mobil (Karten-Reflow ohne Überlauf) blendet er sich selbst aus.
 */
@Directive({ selector: '[appHScrollSync]', standalone: true })
export class HScrollSyncDirective implements OnDestroy {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private bar: HTMLDivElement | null = null;
  private ro: ResizeObserver | null = null;
  private readonly disposers: Array<() => void> = [];

  constructor() {
    // Nur im Browser (nicht SSR): DOM anlegen, wenn der View gerendert ist.
    afterNextRender(() => this.setup());
  }

  private setup(): void {
    const wrap = this.host.nativeElement;
    const parent = wrap.parentElement;
    if (typeof document === 'undefined' || !parent) return;

    const bar = document.createElement('div');
    bar.setAttribute('aria-hidden', 'true');
    bar.style.cssText = 'overflow-x:auto;overflow-y:hidden;';
    const inner = document.createElement('div');
    inner.style.height = '1px';
    bar.appendChild(inner);
    parent.insertBefore(bar, wrap);
    this.bar = bar;

    // scrollLeft beidseitig spiegeln. Die Gleichheits-Prüfung verhindert Ping-Pong:
    // das gespiegelte scroll-Event findet beide Werte identisch vor und setzt nichts mehr.
    const mirror = (from: HTMLElement, to: HTMLElement): void => {
      if (to.scrollLeft !== from.scrollLeft) to.scrollLeft = from.scrollLeft;
    };
    const onWrap = (): void => mirror(wrap, bar);
    const onBar = (): void => mirror(bar, wrap);
    wrap.addEventListener('scroll', onWrap, { passive: true });
    bar.addEventListener('scroll', onBar, { passive: true });
    this.disposers.push(() => wrap.removeEventListener('scroll', onWrap));
    this.disposers.push(() => bar.removeEventListener('scroll', onBar));

    const update = (): void => {
      const full = wrap.scrollWidth;
      inner.style.width = `${full}px`;
      // Kein Überlauf (z.B. mobiler Karten-Reflow) → Leiste ausblenden.
      bar.style.display = full > wrap.clientWidth + 1 ? 'block' : 'none';
    };
    update();
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(() => update());
      ro.observe(wrap);
      const table = wrap.firstElementChild;
      if (table) ro.observe(table);
      this.ro = ro;
    }
  }

  ngOnDestroy(): void {
    this.ro?.disconnect();
    for (const dispose of this.disposers) dispose();
    this.bar?.remove();
  }
}
