import { TestBed } from '@angular/core/testing';
import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { firstValueFrom } from 'rxjs';
import { USE_MOCK_API } from './api.config';
import { mockApiInterceptor } from './mock-api.interceptor';

const PLANNED = '/api/meetings/d0000000-0000-0000-0000-000000000002';

async function plannedTimes(): Promise<{ startTime: string | null; endTime: string | null }> {
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(withInterceptors([mockApiInterceptor])),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: true },
    ],
  });
  return firstValueFrom(
    TestBed.inject(HttpClient).get<{ startTime: string | null; endTime: string | null }>(PLANNED),
  );
}

/** `localStorage.mockNoStart` drops the start and end time of the planned meeting (§ 001142). */
describe('mock planned meeting without a start time', () => {
  afterEach(() => {
    localStorage.removeItem('mockNoStart');
    jest.restoreAllMocks();
    TestBed.resetTestingModule();
  });

  it('keeps the times without the switch', async () => {
    const m = await plannedTimes();
    expect(m.startTime).toBe('17:30:00');
    expect(m.endTime).toBe('19:00:00');
  });

  it('drops the times with the switch', async () => {
    localStorage.setItem('mockNoStart', '1');
    const m = await plannedTimes();
    expect(m.startTime).toBeNull();
    expect(m.endTime).toBeNull();
  });

  it('keeps the times when the storage cannot be read', async () => {
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const m = await plannedTimes();
    expect(m.startTime).toBe('17:30:00');
  });
});
