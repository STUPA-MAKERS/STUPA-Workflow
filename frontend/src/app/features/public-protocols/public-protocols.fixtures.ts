import type {
  PublicProtocolDetail,
  PublicProtocolPage,
  PublicProtocolSummary,
} from './public-protocols.models';

/** A protocol of the list, for the specs. */
export function summaryFixture(over: Partial<PublicProtocolSummary> = {}): PublicProtocolSummary {
  return {
    id: 'p-1',
    title: '34. Sitzung des Studierendenparlaments',
    date: '2026-09-29',
    semester: 'ss-2026',
    finalizedAt: '2026-10-02T10:00:00Z',
    gremium: { id: 'g-1', name: 'Studierendenparlament', slug: 'stupa' },
    tops: [
      { number: 1, title: 'Begrüßung', nonPublic: false, results: [] },
      { number: 2, title: 'Haushalt 2027', nonPublic: false, results: ['passed'] },
      { number: 3, title: null, nonPublic: true, results: [] },
      { number: 4, title: 'Sommerkino', nonPublic: false, results: ['rejected'] },
    ],
    hasPdf: true,
    pdfSize: 217_088,
    ...over,
  };
}

/** One page of the list, for the specs. */
export function pageFixture(
  items: PublicProtocolSummary[],
  total = items.length,
  offset = 0,
): PublicProtocolPage {
  return { items, total, limit: 20, offset };
}

/** One protocol in detail, for the specs. */
export function detailFixture(over: Partial<PublicProtocolDetail> = {}): PublicProtocolDetail {
  return {
    ...summaryFixture(),
    attendance: { present: 23, excused: 6, absent: 2, guests: 0 },
    markdown: null,
    tops: [
      {
        number: 1,
        title: 'Begrüßung',
        nonPublic: false,
        results: [],
        markdown: 'Die Sitzung beginnt um **18:00**.',
        decisions: [],
      },
      {
        number: 2,
        title: 'Haushalt 2027',
        nonPublic: false,
        results: ['passed'],
        markdown: null,
        decisions: [
          {
            question: 'Soll der Haushalt beschlossen werden?',
            counts: { nein: 3, ja: 18, enthaltung: 2 },
            result: 'passed',
            majorityRule: 'simple',
            secret: false,
          },
          {
            question: null,
            counts: { ja: 4, nein: 9 },
            result: 'rejected',
            majorityRule: 'two_thirds',
            secret: true,
          },
          {
            question: 'Offen?',
            counts: { ja: 0 },
            result: null,
            majorityRule: 'absolute',
            secret: false,
          },
        ],
      },
      { number: 3, title: null, nonPublic: true, results: [], markdown: null, decisions: [] },
      { number: 4, title: 'Verschiedenes', nonPublic: false, results: [], markdown: null, decisions: [] },
    ],
    ...over,
  };
}
