import { swipeFrom } from './row-swipe';

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
