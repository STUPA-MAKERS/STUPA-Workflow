import { EventsRefresh } from './events-refresh';

describe('EventsRefresh', () => {
  it('tells each listener about a change', () => {
    const refresh = new EventsRefresh();
    const seen = jest.fn();
    refresh.changed.subscribe(seen);
    refresh.touch();
    expect(seen).toHaveBeenCalledTimes(1);
  });
});
