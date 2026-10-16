import { TicketsPageService } from './tickets-page.service';

describe('TicketsPageService', () => {
  it('starts in one pane and passes a change of the detail to the list', () => {
    const page = new TicketsPageService();
    expect(page.split()).toBe(false);
    const seen: string[] = [];
    page.changed$.subscribe((id) => seen.push(id));
    page.notify('t1');
    expect(seen).toEqual(['t1']);
  });
});
