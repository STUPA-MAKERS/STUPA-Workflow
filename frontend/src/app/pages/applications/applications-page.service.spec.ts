import { ApplicationsPageService, type ApplicationChange } from './applications-page.service';

describe('ApplicationsPageService', () => {
  it('starts with one pane at a time', () => {
    expect(new ApplicationsPageService().split()).toBe(false);
  });

  it('passes a change on to every listener', () => {
    const page = new ApplicationsPageService();
    const seen: ApplicationChange[] = [];
    page.changes$.subscribe((c) => seen.push(c));
    page.notify({ id: 'a', kind: 'deleted', source: 'detail' });
    expect(seen).toEqual([{ id: 'a', kind: 'deleted', source: 'detail' }]);
  });
});
