import { TestBed } from '@angular/core/testing';
import { Component } from '@angular/core';
import { openWindowClock, openWindowState, openWindowWhen } from './open-window.util';

const NOW = Date.parse('2026-10-20T15:30:00Z');
const iso = (min: number): string => new Date(NOW + min * 60_000).toISOString();

describe('openWindowState', () => {
  it('is tooEarly before opensAt, early before confirmUntil, else ok', () => {
    expect(openWindowState({ opensAt: iso(1), confirmUntil: iso(50) }, NOW)).toBe('tooEarly');
    expect(openWindowState({ opensAt: iso(0), confirmUntil: iso(50) }, NOW)).toBe('early');
    expect(openWindowState({ opensAt: iso(-60), confirmUntil: iso(0) }, NOW)).toBe('ok');
  });

  it('is ok without a window or with a broken value', () => {
    expect(openWindowState({ opensAt: null, confirmUntil: null }, NOW)).toBe('ok');
    expect(openWindowState({ opensAt: 'nonsense', confirmUntil: 'nonsense' }, NOW)).toBe('ok');
  });
});

describe('openWindowWhen', () => {
  it('names the time on the same day and adds the day otherwise', () => {
    const local = new Date(2026, 9, 20, 12, 0);
    const sameDay = new Date(2026, 9, 20, 17, 5).toISOString();
    const nextDay = new Date(2026, 9, 21, 17, 5).toISOString();
    expect(openWindowWhen(sameDay, local.getTime(), 'de')).toBe('17:05');
    expect(openWindowWhen(nextDay, local.getTime(), 'de')).toBe('21.10., 17:05');
  });
});

describe('openWindowClock', () => {
  @Component({ selector: 'app-clock-host', standalone: true, template: '' })
  class Host {
    readonly now = openWindowClock(1000);
  }

  afterEach(() => jest.useRealTimers());

  it('ticks and stops with its host', () => {
    jest.useFakeTimers();
    jest.setSystemTime(NOW);
    const fixture = TestBed.createComponent(Host);
    const clock = fixture.componentInstance.now;
    expect(clock()).toBe(NOW);
    jest.advanceTimersByTime(1000);
    expect(clock()).toBe(NOW + 1000);
    fixture.destroy();
    jest.advanceTimersByTime(5000);
    expect(clock()).toBe(NOW + 1000);
  });
});
