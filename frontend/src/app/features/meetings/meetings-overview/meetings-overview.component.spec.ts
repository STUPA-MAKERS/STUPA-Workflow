import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import { AuthService } from '@core/auth/auth.service';
import { WsService } from '@core/ws/ws.service';
import { MeetingAgendaService } from '../meeting-agenda.service';
import { MeetingDialogsService } from '../meeting-dialogs.service';
import { MeetingSessionService } from '../meeting-session.service';
import { MeetingsTimelineService } from '../meetings-timeline.service';
import { MeetingsOverviewComponent } from './meetings-overview.component';

async function setup(opts: { managed?: string[] } = {}) {
  const view = await render(MeetingsOverviewComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([{ path: '**', children: [] }]),
      MeetingsTimelineService,
      MeetingDialogsService,
      MeetingSessionService,
      MeetingAgendaService,
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
  http.match('/api/meetings/committees').forEach((r) => r.flush([]));
  return { ...view, http };
}

describe('MeetingsOverviewComponent', () => {
  /** The month grid is on the Kalender page (§ 000710). */
  it('shows the list and no switch to a calendar view', async () => {
    const { fixture } = await setup();
    expect(fixture.nativeElement.querySelector('app-meetings-list')).not.toBeNull();
    expect(screen.queryByRole('radiogroup')).toBeNull();
    expect(screen.queryByRole('radio', { name: 'Kalender' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Kalender-Abo' })).toBeNull();
  });

  it('opens the create dialog from the list, with the right to create only', async () => {
    const { http } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Sitzung anlegen' }));
    expect(screen.getByRole('dialog', { name: 'Sitzung anlegen' })).toBeInTheDocument();
    http.match('/api/committees').forEach((r) => r.flush([]));
  });

  it('offers no create without the right', async () => {
    await setup({ managed: [] });
    expect(screen.queryByRole('button', { name: 'Sitzung anlegen' })).toBeNull();
  });
});
