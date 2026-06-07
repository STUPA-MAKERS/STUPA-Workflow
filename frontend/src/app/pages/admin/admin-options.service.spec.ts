import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { USE_MOCK_API } from '@core/api/api.config';
import { AdminOptionsService } from './admin-options.service';

describe('AdminOptionsService — mock mode', () => {
  function svc(): AdminOptionsService {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: true },
      ],
    });
    return TestBed.inject(AdminOptionsService);
  }

  it('maps gremien to {value,label} options', async () => {
    const opts = await firstValueFrom(svc().gremiumOptions());
    expect(opts.length).toBeGreaterThan(0);
    expect(opts[0]).toEqual(expect.objectContaining({ value: expect.any(String), label: expect.any(String) }));
  });

  it('falls back to the seed role list when the API yields none', async () => {
    const opts = await firstValueFrom(svc().roleOptions());
    expect(opts.map((o) => o.value)).toContain('member');
    expect(opts.find((o) => o.value === 'member')?.label).toBeTruthy();
  });

  it('humanizes event names into options', () => {
    const opts = svc().eventOptions();
    expect(opts.find((o) => o.value === 'status_changed')?.label).toBe('Status changed');
  });

  it('provides recipient-kind and guard-operator options', () => {
    const s = svc();
    expect(s.recipientKindOptions().map((o) => o.value)).toEqual(['applicant', 'role', 'group']);
    expect(s.guardOperatorOptions().length).toBeGreaterThan(0);
  });
});
