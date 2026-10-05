import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import { AuthService } from '@core/auth/auth.service';
import { WsService } from '@core/ws/ws.service';
import { MEDIA } from '@stupa-makers/ui-kit';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
import { PageFrameService } from '../../../layout/page-frame.service';
import { MeetingAgendaService } from '../meeting-agenda.service';
import { MeetingDialogsService } from '../meeting-dialogs.service';
import { MeetingSessionService } from '../meeting-session.service';
import { OVERVIEW_NOW, VIEW_STORAGE_KEY } from '../meetings-overview.util';
import { MeetingsTimelineService } from '../meetings-timeline.service';
import { MeetingsOverviewComponent } from './meetings-overview.component';

let restoreMedia: (() => void) | null = null;
afterEach(() => {
  restoreMedia?.();
  restoreMedia = null;
  localStorage.clear();
});

async function setup(opts: { media?: string[]; view?: string; managed?: string[] } = {}) {
  if (opts.media) restoreMedia = matchMediaQueries(...opts.media);
  if (opts.view) localStorage.setItem(VIEW_STORAGE_KEY, opts.view);
  const view = await render(MeetingsOverviewComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([{ path: '**', children: [] }]),
      MeetingsTimelineService,
      MeetingDialogsService,
      MeetingSessionService,
      MeetingAgendaService,
      { provide: OVERVIEW_NOW, useValue: () => new Date(2026, 8, 29, 18, 50) },
      { provide: USE_MOCK_API, useValue: false },
      {
        provide: AuthService,
        useValue: {
          can: () => false,
          isAdmin: () => false,
          gremien: () => [{ id: 'g-1', name: 'StuPa' }],
          sessionManageGremien: () => opts.managed ?? ['g-1'],
          inSubstitutePool: () => false,
        },
      },
      { provide: WsService, useValue: {} },
    ],
  });
  const injector = view.fixture.debugElement.injector;
  const http = injector.get(HttpTestingController);
  const frame = injector.get(PageFrameService);
  http.match('/api/meetings/gremien').forEach((r) => r.flush([]));
  return { ...view, http, frame };
}

describe('MeetingsOverviewComponent', () => {
  it('shows the list by default and keeps a switch to the calendar per browser', async () => {
    const { fixture, http } = await setup();
    expect(fixture.nativeElement.querySelector('app-meetings-list')).not.toBeNull();
    expect(fixture.componentInstance.pane()).toBe(false);
    await userEvent.click(screen.getByRole('radio', { name: 'Kalender' }));
    fixture.detectChanges();
    expect(localStorage.getItem(VIEW_STORAGE_KEY)).toBe('calendar');
    expect(fixture.nativeElement.querySelector('app-meetings-calendar')).not.toBeNull();
    http.match((r) => r.url === '/api/meetings').forEach((r) => r.flush([]));
    // The narrow calendar scrolls as a page.
    expect(fixture.componentInstance.pane()).toBe(false);
  });

  it('opens the calendar that the browser chose, as a pane page when wide', async () => {
    const { fixture, http, frame } = await setup({ view: 'calendar', media: [MEDIA.wide] });
    http.match((r) => r.url === '/api/meetings').forEach((r) => r.flush([]));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-meetings-calendar')).not.toBeNull();
    expect(fixture.componentInstance.pane()).toBe(true);
    expect(frame.fill()).toBe(true);
    fixture.destroy();
    expect(frame.fill()).toBe(false);
  });

  it('is a pane page when the list stands beside the detail', async () => {
    const { fixture } = await setup({ media: [MEDIA.wide] });
    fixture.detectChanges();
    expect(fixture.componentInstance.pane()).toBe(true);
  });

  it('shows the list on a phone, whatever the browser chose', async () => {
    const { fixture } = await setup({ view: 'calendar', media: [MEDIA.phone] });
    expect(fixture.nativeElement.querySelector('app-meetings-calendar')).toBeNull();
    expect(fixture.nativeElement.querySelector('app-meetings-list')).not.toBeNull();
  });

  it('opens the create dialog from the list, with the right to create only', async () => {
    const { http } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Neue Sitzung' }));
    expect(screen.getByRole('dialog', { name: 'Sitzung anlegen' })).toBeInTheDocument();
    http.match('/api/gremien').forEach((r) => r.flush([]));
  });

  it('offers no create without the right', async () => {
    await setup({ managed: [] });
    expect(screen.queryByRole('button', { name: 'Neue Sitzung' })).toBeNull();
  });
});
