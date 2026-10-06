import { TestBed } from '@angular/core/testing';
import { CommandPaletteService } from './command-palette.service';

describe('CommandPaletteService', () => {
  it('opens, closes and toggles, and reports each opening once', () => {
    const svc = TestBed.inject(CommandPaletteService);
    const opened = jest.fn();
    svc.opened$.subscribe(opened);

    svc.open();
    svc.open();
    expect(svc.isOpen()).toBe(true);
    expect(opened).toHaveBeenCalledTimes(1);

    svc.toggle();
    expect(svc.isOpen()).toBe(false);
    svc.toggle();
    expect(svc.isOpen()).toBe(true);
    expect(opened).toHaveBeenCalledTimes(2);

    svc.close();
    expect(svc.isOpen()).toBe(false);
  });
});
