import { fireEvent, render, screen } from '@testing-library/angular';
import { PALETTE } from '../budget-color.util';
import { ColourFieldComponent, isColour } from './colour-field.component';

describe('ColourFieldComponent', () => {
  it('takes #rrggbb and the empty text as a colour', () => {
    expect(isColour('')).toBe(true);
    expect(isColour('#A1b2C3')).toBe(true);
    expect(isColour('#abc')).toBe(false);
    expect(isColour('red')).toBe(false);
  });

  it('picks a colour of the palette and tells the form', async () => {
    const picked = jest.fn();
    const view = await render(ColourFieldComponent, { on: { picked } });
    fireEvent.click(view.container.querySelectorAll('.cf__pick')[0]);
    expect(picked).toHaveBeenCalledWith(PALETTE[0].toLowerCase());
    expect(view.fixture.componentInstance.value()).toBe(PALETTE[0].toLowerCase());
  });

  it('clears the colour with the button that shows only for a set colour', async () => {
    const picked = jest.fn();
    await render(ColourFieldComponent, { inputs: { value: '#112233' }, on: { picked } });
    fireEvent.click(screen.getByRole('button', { name: 'Farbe entfernen' }));
    expect(picked).toHaveBeenCalledWith('');
    expect(screen.queryByRole('button', { name: 'Farbe entfernen' })).toBeNull();
  });

  it('lets only a valid hex value leave the field as a choice', async () => {
    const picked = jest.fn();
    const view = await render(ColourFieldComponent, { on: { picked } });
    const c = view.fixture.componentInstance;
    c.value.set('#12');
    c.commit();
    expect(c.invalid()).toBe(true);
    expect(picked).not.toHaveBeenCalled();
    c.value.set('#123456');
    c.commit();
    expect(picked).toHaveBeenCalledWith('#123456');
  });
});
