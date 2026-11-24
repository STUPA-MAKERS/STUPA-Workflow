import { OrdersRefresh } from './orders-refresh';

describe('OrdersRefresh', () => {
  it('tells every listener about a change', () => {
    const refresh = new OrdersRefresh();
    const heard = jest.fn();
    refresh.changed.subscribe(heard);
    refresh.touch();
    refresh.touch();
    expect(heard).toHaveBeenCalledTimes(2);
  });
});
