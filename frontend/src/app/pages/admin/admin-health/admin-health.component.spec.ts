import { of, throwError } from 'rxjs';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { AuthService } from '@core/auth/auth.service';
import { AdminApiService } from '../admin-api.service';
import type { AuditVerification, Backup, BackupList } from '../admin.models';
import { AdminHealthComponent } from './admin-health.component';

function fakeAuth(perms: string[]): Partial<AuthService> {
  const set = new Set(perms);
  return { can: (p: string) => set.has(p), canAny: (...p: string[]) => p.some((x) => set.has(x)) };
}

const ALL = ['audit.read', 'audit.verify', 'backup.manage', 'privacy.manage'];

const CHECK: AuditVerification = {
  id: 'av-1',
  startedAt: '2026-06-07T02:30:00+02:00',
  finishedAt: '2026-06-07T02:30:04+02:00',
  valid: true,
  checked: 18412,
  brokenAt: null,
  reason: null,
  trigger: 'cron',
  triggeredBy: null,
};

function backup(over: Partial<Backup>): Backup {
  return {
    id: 'b',
    kind: 'manual',
    status: 'done',
    createdAt: '2026-06-01T17:45:00+02:00',
    sizeBytes: 433_061_888,
    objectCount: 10,
    pinned: false,
    ...over,
  };
}

function list(items: Backup[], enabled = true): BackupList {
  return { items, enabled, restoreEnabled: true, retentionCount: 14 };
}

async function setup(perms: string[], api: Partial<Record<keyof AdminApiService, jest.Mock>> = {}) {
  const fake = {
    latestAuditVerification: jest.fn(() => of(CHECK)),
    verifyAuditChain: jest.fn(() => of({ valid: true, checked: 12, brokenAt: null, reason: null })),
    listBackups: jest.fn(() =>
      of(list([backup({ id: 'old', createdAt: '2026-05-01T10:00:00+02:00' }), backup({ id: 'new' })])),
    ),
    listErasures: jest.fn(() => of([{ id: 'e-1' }, { id: 'e-2' }])),
    ...api,
  };
  const view = await render(AdminHealthComponent, {
    providers: [
      provideRouter([]),
      { provide: AuthService, useValue: fakeAuth(perms) },
      { provide: AdminApiService, useValue: fake },
    ],
  });
  return { view, api: fake };
}

function tileTexts(container: HTMLElement): string[] {
  return [...container.querySelectorAll('.ah__tile')].map((t) => (t.textContent ?? '').replace(/\s+/g, ' ').trim());
}

describe('AdminHealthComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the three tiles with their links', async () => {
    const { view, api } = await setup(ALL);
    expect(screen.getByRole('heading', { name: 'Zustand' })).toBeInTheDocument();
    const links = screen.getAllByRole('link');
    expect(links.map((l) => l.getAttribute('href'))).toEqual([
      '/admin/audit',
      '/admin/backups',
      '/admin/privacy',
    ]);
    const [audit, back, erasure] = tileTexts(view.container);
    expect(audit).toContain('Audit-Kette intakt');
    expect(audit).toContain('Zuletzt geprüft');
    expect(audit).toContain('18.412 Einträge');
    // The newest archive, not the first of the list.
    expect(back).toContain('Letztes Backup');
    expect(back).toContain('Manuell · Fertig · 413 MB');
    expect(erasure).toContain('2 offene Löschanträge');
    expect(erasure).toContain('Art. 17 DSGVO');
    // The tiles show their own placeholders, so the calls skip the global overlay.
    expect(api.listErasures).toHaveBeenCalledWith('open', { quiet: true });
    expect(api.listBackups).toHaveBeenCalledWith({ quiet: true });
    expect(api.verifyAuditChain).not.toHaveBeenCalled();
  });

  it('shows a broken chain as an error with the entry of the break', async () => {
    const { view } = await setup(['audit.read'], {
      latestAuditVerification: jest.fn(() =>
        of({ ...CHECK, valid: false, brokenAt: 812, reason: 'hash_mismatch' as const }),
      ),
    });
    const tile = view.container.querySelector('.ah__tile');
    expect(tile).toHaveClass('ah__tile--error');
    expect(tile?.textContent).toContain('Audit-Kette unterbrochen');
    expect(tile?.textContent).toContain('Bruch bei Eintrag 812');
  });

  it('checks the chain live before the first stored check, with audit.verify', async () => {
    const { view, api } = await setup(['audit.read', 'audit.verify'], {
      latestAuditVerification: jest.fn(() => of(null)),
    });
    expect(api.verifyAuditChain).toHaveBeenCalled();
    expect(tileTexts(view.container)[0]).toContain('Gerade geprüft · 12 Einträge');
  });

  it('says "not checked yet" without a stored check and without audit.verify', async () => {
    const { view, api } = await setup(['audit.read'], {
      latestAuditVerification: jest.fn(() => of(null)),
    });
    expect(api.verifyAuditChain).not.toHaveBeenCalled();
    expect(tileTexts(view.container)[0]).toContain('Audit-Kette noch nicht geprüft');
  });

  it('gives a muted line when a request fails, never an alarm', async () => {
    const fail = jest.fn(() => throwError(() => new Error('x')));
    const { view } = await setup(ALL, {
      latestAuditVerification: fail,
      listBackups: fail,
      listErasures: fail,
    });
    const texts = tileTexts(view.container);
    expect(texts[0]).toContain('Zustand der Audit-Kette unbekannt');
    expect(texts[1]).toContain('Zustand der Backups unbekannt');
    expect(texts[2]).toContain('Löschanträge unbekannt');
    expect(view.container.querySelectorAll('.ah__tile--muted')).toHaveLength(3);
  });

  it('reports a failed live check', async () => {
    const { view } = await setup(['audit.read', 'audit.verify'], {
      latestAuditVerification: jest.fn(() => of(null)),
      verifyAuditChain: jest.fn(() => throwError(() => new Error('x'))),
    });
    expect(tileTexts(view.container)[0]).toContain('Zustand der Audit-Kette unbekannt');
  });

  it.each([
    ['none', list([]), 'Noch kein Backup'],
    ['not set up', list([], false), 'Backups nicht eingerichtet'],
    ['failed', list([backup({ status: 'failed', sizeBytes: null })]), 'Manuell · Fehlgeschlagen'],
    ['running', list([backup({ status: 'running', sizeBytes: null })]), 'Manuell · Läuft'],
  ])('covers the backup state "%s"', async (_name, l, text) => {
    const { view } = await setup(['backup.manage'], { listBackups: jest.fn(() => of(l)) });
    expect(tileTexts(view.container)[0]).toContain(text);
  });

  it('counts one open erasure request in the singular', async () => {
    const { view } = await setup(['privacy.manage'], { listErasures: jest.fn(() => of([{ id: 'e' }])) });
    expect(tileTexts(view.container)[0]).toContain('1 offener Löschantrag');
  });

  it('says so when no erasure request is open', async () => {
    const { view } = await setup(['privacy.manage'], { listErasures: jest.fn(() => of([])) });
    expect(tileTexts(view.container)[0]).toContain('Keine offenen Löschanträge');
  });

  it('shows only the tiles of the held permissions', async () => {
    const { api } = await setup(['backup.manage']);
    expect(screen.getAllByRole('link')).toHaveLength(1);
    expect(api.latestAuditVerification).not.toHaveBeenCalled();
    expect(api.listErasures).not.toHaveBeenCalled();
  });

  it('renders nothing without any of the permissions', async () => {
    const { view } = await setup([]);
    expect(view.container.querySelector('section')).toBeNull();
  });

  it('shows a placeholder in every tile while its data loads', async () => {
    const { view } = await setup(ALL, {
      latestAuditVerification: jest.fn(() => of()),
      listBackups: jest.fn(() => of()),
      listErasures: jest.fn(() => of()),
    });
    expect(view.container.querySelectorAll('.ah__skel')).toHaveLength(3);
  });

  it('takes the newest of several archives whatever their order', async () => {
    const { view } = await setup(['backup.manage'], {
      listBackups: jest.fn(() =>
        of(
          list([
            backup({ id: 'b2', kind: 'scheduled', createdAt: '2026-06-02T04:00:00+02:00' }),
            backup({ id: 'b1', kind: 'imported', createdAt: '2026-06-01T04:00:00+02:00' }),
            backup({ id: 'b3', kind: 'manual', createdAt: '2026-05-30T04:00:00+02:00' }),
          ]),
        ),
      ),
    });
    expect(tileTexts(view.container)[0]).toContain('Automatisch');
  });

  it('keeps the last finished archive while a newer one runs', async () => {
    const { view } = await setup(['backup.manage'], {
      listBackups: jest.fn(() =>
        of(
          list([
            backup({ id: 'run', status: 'running', sizeBytes: null, createdAt: '2026-06-01T18:46:00+02:00' }),
            backup({ id: 'done', createdAt: '2026-06-01T17:45:00+02:00' }),
          ]),
        ),
      ),
    });
    const tile = view.container.querySelector('.ah__tile');
    expect(tile).toHaveClass('ah__tile--ok');
    expect(tileTexts(view.container)[0]).toContain('Manuell · Fertig · 413 MB');
    expect(tileTexts(view.container)[0]).not.toContain('Läuft');
  });

  it('marks the tile red when an archive after the last finished one failed', async () => {
    const { view } = await setup(['backup.manage'], {
      listBackups: jest.fn(() =>
        of(
          list([
            backup({ id: 'done', createdAt: '2026-06-01T17:45:00+02:00' }),
            backup({ id: 'bad', status: 'failed', sizeBytes: null, createdAt: '2026-06-02T04:00:00+02:00' }),
          ]),
        ),
      ),
    });
    const tile = view.container.querySelector('.ah__tile');
    expect(tile).toHaveClass('ah__tile--error');
    expect(tileTexts(view.container)[0]).toContain('Manuell · Fertig · 413 MB');
    expect(tile?.querySelector('.ah__alert')?.textContent).toContain('Letzte Sicherung fehlgeschlagen');
  });

  it('runs the live chain check only one time per session', async () => {
    const verify = jest.fn(() => of({ valid: true, checked: 12, brokenAt: null, reason: null }));
    const { view } = await setup(['audit.read', 'audit.verify'], {
      latestAuditVerification: jest.fn(() => of(null)),
      verifyAuditChain: verify,
    });
    view.fixture.destroy();
    // A second set of tiles in the same session (a return to /admin) takes the result.
    const second = TestBed.createComponent(AdminHealthComponent);
    second.detectChanges();
    expect(verify).toHaveBeenCalledTimes(1);
    expect((second.nativeElement as HTMLElement).textContent).toContain('Gerade geprüft · 12 Einträge');
  });

  it('shows a placeholder while the data loads', async () => {
    const { view } = await setup(['audit.read'], {
      latestAuditVerification: jest.fn(() => of()),
    });
    expect(view.container.querySelector('.ah__skel')).not.toBeNull();
    expect(screen.getByText('Wird geladen …')).toBeInTheDocument();
  });
});
