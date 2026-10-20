import { ToastService } from '@stupa-makers/ui-kit';
import { deleteAfterUndo, swipeFrom } from './row-swipe';

describe('swipeFrom', () => {
  const sections = [
    { items: [{ id: 'edit', label: 'Bearbeiten', icon: 'edit' as const }] },
    {
      items: [
        { id: 'delete', label: 'Löschen', icon: 'trash' as const, danger: true },
        { id: 'off', label: 'Aus', icon: 'x' as const, disabledReason: 'Nicht jetzt' },
        { id: 'bare', label: 'Ohne Symbol' },
      ],
    },
  ];

  it('takes the item of the menu with its label and icon', () => {
    expect(swipeFrom(sections, 'edit')).toEqual({ id: 'edit', label: 'Bearbeiten', icon: 'edit', leaves: false });
    expect(swipeFrom(sections, 'delete', true)).toEqual({ id: 'delete', label: 'Löschen', icon: 'trash', leaves: true });
  });

  it('gives null for a missing, a disabled or an item without an icon', () => {
    expect(swipeFrom(sections, 'paid')).toBeNull();
    expect(swipeFrom(sections, 'off')).toBeNull();
    expect(swipeFrom(sections, 'bare')).toBeNull();
    expect(swipeFrom([], 'edit')).toBeNull();
  });
});

describe('deleteAfterUndo', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it('sends the delete when the toast goes without the undo', () => {
    const toast = new ToastService();
    const send = jest.fn();
    const restore = jest.fn();
    deleteAfterUndo(toast, { message: 'Gelöscht.', undo: 'Rückgängig', send, restore });
    expect(toast.toasts()[0]).toEqual(expect.objectContaining({ message: 'Gelöscht.', action: 'Rückgängig' }));
    jest.advanceTimersByTime(6000);
    expect(send).toHaveBeenCalledTimes(1);
    expect(restore).not.toHaveBeenCalled();
    deleteAfterUndo(toast, { message: 'Gelöscht.', undo: 'Rückgängig', send, restore });
    toast.dismiss(toast.toasts()[0].id);
    expect(send).toHaveBeenCalledTimes(2);
  });

  it('restores the row and sends nothing after the undo', () => {
    const toast = new ToastService();
    const send = jest.fn();
    const restore = jest.fn();
    deleteAfterUndo(toast, { message: 'Gelöscht.', undo: 'Rückgängig', send, restore });
    toast.act(toast.toasts()[0].id);
    jest.advanceTimersByTime(6000);
    expect(restore).toHaveBeenCalledTimes(1);
    expect(send).not.toHaveBeenCalled();
  });
});
