import {
  mapApplication,
  mapApplicationCreated,
  mapApplicationListItem,
  mapApplicationType,
  mapAttachment,
  mapBudgetPotInfo,
  mapBudgetStats,
  mapComment,
  mapMeeting,
  mapProtocol,
  mapSignedUrl,
  mapState,
  mapTimelineEvent,
  mapTransition,
  mapVersion,
  toApplicationCreateBody,
} from './mappers';
import type {
  ApplicationOutWire,
  ApplicationListItemWire,
  ApplicationTypeListItemWire,
  AttachmentOutWire,
  BudgetPotOutWire,
  BudgetStatsOutWire,
  CommentOutWire,
  MeetingOutWire,
  NewApplication,
  ProtocolOutWire,
  StateOutWire,
  TimelineEventOutWire,
  TransitionOutWire,
  VersionOutWire,
} from './models';

const STATE: StateOutWire = {
  id: 's1',
  key: 'submitted',
  label: { de: 'Eingereicht', en: 'Submitted' },
  category: 'open',
  editAllowed: true,
};

describe('mapState', () => {
  it('resolves the i18n label for the requested language', () => {
    expect(mapState(STATE, 'en')?.label).toBe('Submitted');
    expect(mapState(STATE, 'de')?.label).toBe('Eingereicht');
  });

  it('falls back to de for an unknown language', () => {
    expect(mapState(STATE, 'fr')?.label).toBe('Eingereicht');
  });

  it('keeps the structural fields (id/key/category/editAllowed)', () => {
    expect(mapState(STATE, 'de')).toEqual({
      id: 's1',
      key: 'submitted',
      label: 'Eingereicht',
      category: 'open',
      editAllowed: true,
      kind: 'normal',
    });
  });

  it('returns null for null/undefined input', () => {
    expect(mapState(null, 'de')).toBeNull();
    expect(mapState(undefined, 'de')).toBeNull();
  });
});

describe('mapApplication', () => {
  const wire: ApplicationOutWire = {
    id: 'a1',
    typeId: 't1',
    state: STATE,
    gremiumId: 'g1',
    budgetPotId: 'p1',
    amount: '250.00',
    currency: 'EUR',
    data: { title: 'Fest' },
    version: 3,
    lang: 'de',
    createdAt: '2026-06-05T10:00:00Z',
    updatedAt: '2026-06-06T10:00:00Z',
    applicant: { email: 'a@b.de', name: 'Max', anonymized: false },
  };

  it('maps every camelCase field into the view model 1:1', () => {
    const view = mapApplication(wire, 'de');
    expect(view).toEqual({
      id: 'a1',
      typeId: 't1',
      state: { id: 's1', key: 'submitted', label: 'Eingereicht', category: 'open', editAllowed: true, kind: 'normal' },
      gremiumId: 'g1',
      budgetPotId: 'p1',
      amount: '250.00',
      currency: 'EUR',
      data: { title: 'Fest' },
      version: 3,
      lang: 'de',
      createdAt: '2026-06-05T10:00:00Z',
      updatedAt: '2026-06-06T10:00:00Z',
      applicant: { email: 'a@b.de', name: 'Max', anonymized: false },
    });
  });

  it('normalises omitted optionals to null and missing data to {}', () => {
    const minimal: ApplicationOutWire = {
      id: 'a2',
      typeId: 't2',
      data: { x: 1 },
      version: 1,
      createdAt: '2026-06-05T10:00:00Z',
      updatedAt: '2026-06-05T10:00:00Z',
    };
    const view = mapApplication(minimal, 'de');
    expect(view.state).toBeNull();
    expect(view.gremiumId).toBeNull();
    expect(view.budgetPotId).toBeNull();
    expect(view.amount).toBeNull();
    expect(view.currency).toBeNull();
    expect(view.lang).toBeNull();
    expect(view.applicant).toBeNull();
    expect(view.data).toEqual({ x: 1 });
  });
});

describe('mapApplicationListItem', () => {
  it('maps the list item and resolves the state label', () => {
    const wire: ApplicationListItemWire = {
      id: 'a1',
      typeId: 't1',
      state: STATE,
      amount: '10.00',
      currency: 'EUR',
      createdAt: '2026-06-05T10:00:00Z',
      updatedAt: '2026-06-05T10:00:00Z',
    };
    const view = mapApplicationListItem(wire, 'en');
    expect(view.state?.label).toBe('Submitted');
    expect(view.gremiumId).toBeNull();
    expect(view.budgetPotId).toBeNull();
    expect(view.amount).toBe('10.00');
  });
});

describe('mapTimelineEvent', () => {
  it('derives the label from the resolved toState', () => {
    const wire: TimelineEventOutWire = {
      fromStateId: null,
      toStateId: 's1',
      toState: STATE,
      actor: 'Referat',
      at: '2026-06-05T10:00:00Z',
      note: 'ok',
    };
    const view = mapTimelineEvent(wire, 'en');
    expect(view).toEqual({
      toStateId: 's1',
      toState: { id: 's1', key: 'submitted', label: 'Submitted', category: 'open', editAllowed: true, kind: 'normal' },
      label: 'Submitted',
      actor: 'Referat',
      at: '2026-06-05T10:00:00Z',
      note: 'ok',
    });
  });

  it('falls back to an empty label and null defaults when toState is absent', () => {
    const wire: TimelineEventOutWire = { toStateId: 's9', at: '2026-06-05T10:00:00Z' };
    const view = mapTimelineEvent(wire, 'de');
    expect(view.label).toBe('');
    expect(view.toState).toBeNull();
    expect(view.actor).toBeNull();
    expect(view.note).toBeNull();
  });
});

describe('mapComment', () => {
  it('derives isPublic=true from visibility "public"', () => {
    const wire: CommentOutWire = {
      id: 'c1',
      author: 'Referat',
      authorKind: 'principal',
      body: 'Hallo',
      visibility: 'public',
      at: '2026-06-05T13:00:00Z',
    };
    expect(mapComment(wire)).toEqual({
      id: 'c1',
      author: 'Referat',
      authorKind: 'principal',
      body: 'Hallo',
      visibility: 'public',
      isPublic: true,
      at: '2026-06-05T13:00:00Z',
    });
  });

  it('derives isPublic=false for an internal comment and null author', () => {
    const wire: CommentOutWire = {
      id: 'c2',
      authorKind: 'applicant',
      body: 'intern',
      visibility: 'internal',
      at: '2026-06-05T13:00:00Z',
    };
    const view = mapComment(wire);
    expect(view.isPublic).toBe(false);
    expect(view.author).toBeNull();
  });
});

describe('mapApplicationType', () => {
  it('maps public fields and defaults admin-only fields to null', () => {
    const wire: ApplicationTypeListItemWire = {
      id: 't1',
      name: 'Finanzantrag',
      hasBudget: true,
      active: true,
      activeFormVersionId: 'v1',
    };
    expect(mapApplicationType(wire)).toEqual({
      id: 't1',
      name: 'Finanzantrag',
      active: true,
      hasBudget: true,
      activeFormVersionId: 'v1',
      key: null,
      gremiumId: null,
    });
  });

  it('passes admin fields through when present', () => {
    const wire: ApplicationTypeListItemWire = {
      id: 't1',
      name: 'Finanzantrag',
      hasBudget: false,
      active: false,
      key: 'fin',
      gremiumId: 'g1',
    };
    const view = mapApplicationType(wire);
    expect(view.key).toBe('fin');
    expect(view.gremiumId).toBe('g1');
    expect(view.activeFormVersionId).toBeNull();
  });
});

describe('mapTransition', () => {
  it('resolves the i18n label and keeps the state ids', () => {
    const wire: TransitionOutWire = {
      id: 'tr1',
      fromStateId: 's1',
      toStateId: 's2',
      label: { de: 'Annehmen', en: 'Accept' },
    };
    expect(mapTransition(wire, 'en')).toEqual({
      id: 'tr1',
      fromStateId: 's1',
      toStateId: 's2',
      label: 'Accept',
    });
  });
});

describe('mapApplicationCreated', () => {
  it('unwraps applicationId', () => {
    expect(mapApplicationCreated({ applicationId: 'a1' })).toEqual({ applicationId: 'a1' });
  });
});

describe('toApplicationCreateBody', () => {
  it('builds the camelCase request body', () => {
    const input: NewApplication = {
      typeId: 't1',
      budgetPotId: 'p1',
      data: { title: 'Fest' },
      applicantEmail: 'a@b.de',
      applicantName: 'Max',
      lang: 'de',
      altcha: 'sol',
    };
    expect(toApplicationCreateBody(input)).toEqual({
      typeId: 't1',
      budgetPotId: 'p1',
      data: { title: 'Fest' },
      applicantEmail: 'a@b.de',
      applicantName: 'Max',
      lang: 'de',
      altcha: 'sol',
    });
  });

  it('defaults omitted optionals (budgetPotId/applicantName) to null', () => {
    const input: NewApplication = {
      typeId: 't1',
      data: {},
      applicantEmail: 'a@b.de',
      lang: 'en',
      altcha: 'sol',
    };
    const body = toApplicationCreateBody(input);
    expect(body.budgetPotId).toBeNull();
    expect(body.applicantName).toBeNull();
  });
});

describe('mapVersion', () => {
  it('passes a null diff through (e.g. the first version)', () => {
    const wire: VersionOutWire = {
      version: 1,
      data: { title: 'Alt' },
      diff: null,
      changedBy: null,
      at: '2026-06-01T10:00:00Z',
    };
    const v = mapVersion(wire);
    expect(v.diff).toBeNull();
    expect(v.changedBy).toBeNull();
    expect(v.data).toEqual({ title: 'Alt' });
  });

  it('flattens the diff maps into keyed lists', () => {
    const wire: VersionOutWire = {
      version: 2,
      data: { title: 'Neu', note: 'x' },
      diff: {
        added: { note: 'x' },
        removed: { obsolete: 'y' },
        changed: { title: { old: 'Alt', new: 'Neu' } },
      },
      changedBy: 'Mia',
      at: '2026-06-02T10:00:00Z',
    };
    const v = mapVersion(wire);
    expect(v.diff?.added).toEqual([{ key: 'note', value: 'x' }]);
    expect(v.diff?.removed).toEqual([{ key: 'obsolete', value: 'y' }]);
    expect(v.diff?.changed).toEqual([{ key: 'title', old: 'Alt', new: 'Neu' }]);
  });

  it('tolerates missing diff sub-maps', () => {
    const wire = {
      version: 3,
      data: {},
      diff: { added: { a: 1 } },
      at: '2026-06-03T10:00:00Z',
    } as unknown as VersionOutWire;
    const v = mapVersion(wire);
    expect(v.diff?.added).toEqual([{ key: 'a', value: 1 }]);
    expect(v.diff?.removed).toEqual([]);
    expect(v.diff?.changed).toEqual([]);
  });
});

describe('mapAttachment', () => {
  const base: AttachmentOutWire = {
    id: 'att-1',
    filename: 'plan.pdf',
    mime: 'application/pdf',
    size: 2048,
    scanned: false,
    is_comparison_offer: false,
  };

  it('maps snake_case is_comparison_offer to camelCase', () => {
    const a = mapAttachment({ ...base, is_comparison_offer: true });
    expect(a.isComparisonOffer).toBe(true);
    expect(a.filename).toBe('plan.pdf');
  });

  it('derives scanState=scanning while the scan is pending', () => {
    expect(mapAttachment(base).scanState).toBe('scanning');
  });

  it('derives scanState=clean once scanned=true', () => {
    expect(mapAttachment({ ...base, scanned: true }).scanState).toBe('clean');
  });
});

describe('mapSignedUrl', () => {
  it('passes the url and expiry through', () => {
    expect(mapSignedUrl({ url: 'https://minio/x?sig=1', expiresIn: 60 })).toEqual({
      url: 'https://minio/x?sig=1',
      expiresIn: 60,
    });
  });
});

describe('mapMeeting', () => {
  it('maps the session state and normalises optional fields', () => {
    const wire: MeetingOutWire = {
      id: 'm-1',
      title: 'Sitzung',
      status: 'live',
      activeApplicationId: 'app-1',
      votes: [
        {
          id: 'v-1',
          applicationId: 'app-1',
          title: 'Antrag A',
          status: 'open',
          counts: { ja: 5 },
          leading: 'ja',
        },
      ],
      createdAt: '2026-06-12T17:00:00Z',
    };
    const m = mapMeeting(wire);
    expect(m.activeApplicationId).toBe('app-1');
    expect(m.gremiumId).toBeNull();
    expect(m.protocolId).toBeNull();
    expect(m.votes).toHaveLength(1);
    expect(m.votes[0].result).toBeNull();
    expect(m.votes[0].closesAt).toBeNull();
  });

  it('defaults a missing vote list to an empty array', () => {
    const wire = {
      id: 'm-2',
      title: 'Leer',
      status: 'planned',
      createdAt: '2026-06-12T17:00:00Z',
    } as unknown as MeetingOutWire;
    expect(mapMeeting(wire).votes).toEqual([]);
  });
});

describe('mapProtocol', () => {
  it('derives isFinal from the status', () => {
    const wire: ProtocolOutWire = {
      id: 'p-1',
      meetingId: 'm-1',
      markdown: '# Titel',
      status: 'final',
      pdfUrl: 'https://example/p.pdf',
      sentAt: '2026-06-12T19:00:00Z',
    };
    const p = mapProtocol(wire);
    expect(p.isFinal).toBe(true);
    expect(p.pdfUrl).toBe('https://example/p.pdf');
  });

  it('treats a draft as not final and normalises missing fields', () => {
    const p = mapProtocol({
      id: 'p-2',
      meetingId: 'm-1',
      markdown: '',
      status: 'draft',
    } as ProtocolOutWire);
    expect(p.isFinal).toBe(false);
    expect(p.pdfUrl).toBeNull();
    expect(p.sentAt).toBeNull();
  });
});

describe('mapBudgetPotInfo', () => {
  const wire: BudgetPotOutWire = {
    id: 'pot-1',
    gremiumId: 'g1',
    name: 'Veranstaltungen',
    total: '10000.00',
    currency: 'EUR',
    period: '2026',
    active: true,
  };

  it('parses the Decimal-string total into a number', () => {
    const pot = mapBudgetPotInfo(wire);
    expect(pot.total).toBe(10000);
    expect(pot.name).toBe('Veranstaltungen');
  });

  it('keeps an unlimited pot total as null', () => {
    expect(mapBudgetPotInfo({ ...wire, total: null }).total).toBeNull();
  });
});

describe('mapBudgetStats', () => {
  const wire: BudgetStatsOutWire = {
    pots: [
      {
        budgetPotId: 'pot-1',
        period: '2026',
        total: '10000.00',
        currency: 'EUR',
        requested: '4200.00',
        reserved: '1500.00',
        approved: '3000.00',
        paid: '2000.00',
        committed: '6500.00',
        available: '3500.00',
      },
    ],
    statusDistribution: [{ gremiumId: 'g1', stateId: 's1', count: 5 }],
  };

  it('converts money strings to numbers across all stages', () => {
    const stats = mapBudgetStats(wire);
    expect(stats.pots[0].committed).toBe(6500);
    expect(stats.pots[0].available).toBe(3500);
    expect(stats.statusDistribution[0].count).toBe(5);
  });

  it('resolves the pot name from the supplied map', () => {
    const stats = mapBudgetStats(wire, new Map([['pot-1', 'Veranstaltungen']]));
    expect(stats.pots[0].name).toBe('Veranstaltungen');
  });

  it('falls back to a shortened id when no name is known', () => {
    const stats = mapBudgetStats({
      ...wire,
      pots: [{ ...wire.pots[0], budgetPotId: 'abcdefgh-ijkl' }],
    });
    expect(stats.pots[0].name).toBe('abcdefgh…');
  });

  it('defaults a missing/blank money field to zero (no NaN leak)', () => {
    const stats = mapBudgetStats({
      ...wire,
      pots: [{ ...wire.pots[0], requested: '' }],
    });
    expect(stats.pots[0].requested).toBe(0);
  });
});
