import { TOUCH_SELECTABLE, guardTouchContextMenu } from './touch-context-menu';

/** A pointerdown of this type on `el`; jsdom has no PointerEvent, so a MouseEvent carries it. */
function down(el: Element, pointerType: string): void {
  const e = new MouseEvent('pointerdown', { bubbles: true });
  Object.defineProperty(e, 'pointerType', { value: pointerType });
  el.dispatchEvent(e);
}

function menu(el: Element): MouseEvent {
  const e = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
  el.dispatchEvent(e);
  return e;
}

describe('guardTouchContextMenu', () => {
  let remove: () => void;
  beforeEach(() => {
    document.body.innerHTML = `
      <a class="row" href="/todos/1"><span class="title">Druckkosten</span></a>
      <input class="field" />
      <div class="mdv"><p class="para">Text</p></div>
      <dl class="kv"><dt class="label">IBAN</dt><dd class="value">DE02 1203</dd></dl>
      <span class="selectable code">ABC-123</span>`;
    remove = guardTouchContextMenu(document);
  });
  afterEach(() => {
    remove();
    document.body.innerHTML = '';
  });
  const q = (s: string) => document.querySelector(s)!;

  it('stops the link menu of a long press on a row and on interface text', () => {
    down(q('.title'), 'touch');
    expect(menu(q('.title')).defaultPrevented).toBe(true);
    expect(menu(q('.label')).defaultPrevented).toBe(true);
  });

  it('keeps the menu on content: a field, Markdown, a value and a selectable element', () => {
    down(q('.field'), 'touch');
    for (const s of ['.field', '.para', '.value', '.code']) expect(menu(q(s)).defaultPrevented).toBe(false);
    expect(TOUCH_SELECTABLE).toContain('.chat__text');
  });

  it('keeps the right click of a mouse and a pen, and still lets a handler of the row see the event', () => {
    down(q('.title'), 'mouse');
    expect(menu(q('.title')).defaultPrevented).toBe(false);
    down(q('.title'), 'pen');
    expect(menu(q('.title')).defaultPrevented).toBe(false);
    const own = jest.fn();
    q('.row').addEventListener('contextmenu', own);
    down(q('.title'), 'touch');
    menu(q('.title'));
    expect(own).toHaveBeenCalled();
    // A target that is not an element (the document) is interface too.
    const e = new MouseEvent('contextmenu', { cancelable: true });
    document.dispatchEvent(e);
    expect(e.defaultPrevented).toBe(true);
  });

  it('removes its listeners', () => {
    remove();
    down(q('.title'), 'touch');
    expect(menu(q('.title')).defaultPrevented).toBe(false);
    remove = () => undefined;
  });
});
