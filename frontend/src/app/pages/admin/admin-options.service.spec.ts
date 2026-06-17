import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom, of } from 'rxjs';
import { USE_MOCK_API } from '@core/api/api.config';
import { AdminApiService } from './admin-api.service';
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

  it('maps application types to {value,label} options (#69)', async () => {
    const opts = await firstValueFrom(svc().applicationTypeOptions());
    expect(opts.length).toBe(2);
    expect(opts[0]).toEqual(expect.objectContaining({ value: expect.any(String), label: expect.any(String) }));
    // value is the type id, label the display name
    expect(opts.find((o) => o.label === 'Finanzantrag')).toBeTruthy();
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
    // guard operator values equal their labels (value == key)
    expect(s.guardOperatorOptions().every((o) => o.value === o.label)).toBe(true);
  });
});

describe('AdminOptionsService — roleOptions non-empty branch', () => {
  it('uses the API roles (not the seed fallback) and resolves the locale label', async () => {
    const fakeApi = {
      listRoles: () =>
        of([{ id: 'r1', key: 'chair', label: { de: 'Vorsitz', en: 'Chair' }, permissions: [] }]),
    } as unknown as AdminApiService;
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: true },
        { provide: AdminApiService, useValue: fakeApi },
      ],
    });
    const s = TestBed.inject(AdminOptionsService);
    const opts = await firstValueFrom(s.roleOptions());
    expect(opts).toEqual([{ value: 'chair', label: expect.any(String) }]);
    // not falling back to the seed → only the single API role is present
    expect(opts).toHaveLength(1);
    TestBed.inject(HttpTestingController).verify();
  });

  it('falls back to the seed list when the API returns an empty array', async () => {
    const fakeApi = { listRoles: () => of([]) } as unknown as AdminApiService;
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: true },
        { provide: AdminApiService, useValue: fakeApi },
      ],
    });
    const s = TestBed.inject(AdminOptionsService);
    const opts = await firstValueFrom(s.roleOptions());
    // empty API → MOCK_ROLES fallback (member/referent/vorstand/admin)
    expect(opts.map((o) => o.value)).toContain('member');
    expect(opts.length).toBeGreaterThan(1);
    TestBed.inject(HttpTestingController).verify();
  });
});
