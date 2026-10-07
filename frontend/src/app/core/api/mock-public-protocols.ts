/**
 * Mock of the public protocol routes (`/public/gremien`, `/public/protocols…`) for the
 * dev mock mode. Two fictional protocols of one public gremium. The interceptor loads
 * this file on first use.
 */
import type {
  PublicGremium,
  PublicProtocolDetail,
  PublicProtocolPage,
  PublicSemester,
} from '../../features/public-protocols/public-protocols.models';

const GREMIUM = { id: 'g-public-1', name: 'Studierendenparlament', slug: 'stupa' };

const PROTOCOLS: PublicProtocolDetail[] = [
  {
    id: 'pp-0001',
    title: '34. Sitzung des Studierendenparlaments',
    date: '2026-09-29',
    semester: 'ss-2026',
    finalizedAt: '2026-10-02T10:00:00Z',
    gremium: GREMIUM,
    hasPdf: true,
    pdfSize: 217_000,
    attendance: { present: 23, excused: 6, absent: 2, guests: 0 },
    markdown: null,
    tops: [
      { number: 1, title: 'Begrüßung', nonPublic: false, results: [], markdown: 'Die Sitzungsleitung eröffnet die Sitzung um 18:00.', decisions: [] },
      {
        number: 2,
        title: 'Genehmigung der Tagesordnung',
        nonPublic: false,
        results: ['passed'],
        markdown: null,
        decisions: [
          {
            question: 'Soll die Tagesordnung genehmigt werden?',
            counts: { ja: 21, nein: 0, enthaltung: 2 },
            result: 'passed',
            majorityRule: 'simple',
            secret: false,
          },
        ],
      },
      { number: 3, title: null, nonPublic: true, results: [], markdown: null, decisions: [] },
    ],
  },
  {
    id: 'pp-0002',
    title: '33. Sitzung des Studierendenparlaments',
    date: '2026-07-14',
    semester: 'ss-2026',
    finalizedAt: '2026-07-20T10:00:00Z',
    gremium: GREMIUM,
    hasPdf: true,
    pdfSize: 241_000,
    attendance: { present: 25, excused: 4, absent: 2, guests: 0 },
    markdown: '# Freitext\n\nProtokoll ohne Tagesordnung.',
    tops: [],
  },
];

/** The reply of one public route, or `undefined` for an unknown one (404). */
export function mockPublicProtocols(
  method: string,
  path: string,
): { body: unknown } | undefined {
  if (method !== 'GET') return undefined;
  if (path.endsWith('/public/gremien')) {
    const body: PublicGremium[] = [{ ...GREMIUM, protocolCount: PROTOCOLS.length }];
    return { body };
  }
  if (path.endsWith('/public/protocols/semesters')) {
    const body: PublicSemester[] = [{ key: 'ss-2026', count: PROTOCOLS.length }];
    return { body };
  }
  if (path.endsWith('/public/protocols')) {
    const body: PublicProtocolPage = {
      items: PROTOCOLS.map(({ attendance: _a, markdown: _m, ...p }) => ({
        ...p,
        tops: p.tops.map(({ markdown: _tm, decisions: _d, ...t }) => t),
      })),
      total: PROTOCOLS.length,
      limit: 20,
      offset: 0,
    };
    return { body };
  }
  const id = /\/public\/protocols\/([^/]+)$/.exec(path)?.[1];
  const hit = PROTOCOLS.find((p) => p.id === id);
  return hit ? { body: hit } : undefined;
}
