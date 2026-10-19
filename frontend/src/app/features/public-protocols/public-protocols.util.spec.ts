import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Meta } from '@angular/platform-browser';
import {
  longDate,
  meetingDate,
  optionKey,
  orderedCounts,
  parseSemester,
  resultKey,
  semesterLabel,
  shortDate,
  topCounts,
  topParts,
  useNoindex,
} from './public-protocols.util';
import type { PublicDecision } from './public-protocols.models';

const t = (key: string, params?: Record<string, string | number>) =>
  `${key}${params ? JSON.stringify(params) : ''}`;

describe('public protocols util', () => {
  it('reads semester keys', () => {
    expect(parseSemester('ws-2026')).toEqual({ kind: 'ws', year: 2026 });
    expect(parseSemester('ss-2025')).toEqual({ kind: 'ss', year: 2025 });
    expect(parseSemester('2026')).toBeNull();
  });

  it('labels a semester; the winter carries the next year in two digits', () => {
    expect(semesterLabel('ws-2026', t)).toBe('publicProtocols.semester.ws{"year":2026,"next":"27"}');
    expect(semesterLabel('ws-2099', t)).toBe('publicProtocols.semester.ws{"year":2099,"next":"00"}');
    expect(semesterLabel('ss-2026', t)).toBe('publicProtocols.semester.ss{"year":2026}');
    expect(semesterLabel('odd', t)).toBe('odd');
  });

  it('keeps a meeting date on its day and formats it', () => {
    expect(meetingDate('2026-09-29').getDate()).toBe(29);
    expect(longDate('2026-09-29', 'de-DE')).toBe('Di, 29.09.2026');
    expect(longDate('nope', 'de-DE')).toBe('');
    expect(shortDate('2026-10-02T10:00:00Z', 'de-DE')).toBe('02.10.2026');
    expect(shortDate(null, 'de-DE')).toBe('');
    expect(shortDate('nope', 'de-DE')).toBe('');
  });

  it('counts the decisions and the skipped non-public items', () => {
    expect(
      topCounts([
        { number: 1, title: 'A', nonPublic: false, results: ['passed', 'rejected'] },
        { number: 2, title: null, nonPublic: true, results: [] },
        { number: 3, title: 'B', nonPublic: false, results: [] },
      ]),
    ).toEqual({ decisions: 2, nonPublic: 1 });
    expect(resultKey('tie')).toBe('vote.result.tie');
  });

  it('orders and names the vote options', () => {
    expect(orderedCounts({ enthaltung: 1, andere: 4, nein: 2, ja: 3 })).toEqual([
      { option: 'ja', count: 3 },
      { option: 'nein', count: 2 },
      { option: 'enthaltung', count: 1 },
      { option: 'andere', count: 4 },
    ]);
    expect(optionKey('Yes')).toBe('vote.option.yes');
    expect(optionKey('no')).toBe('vote.option.no');
    expect(optionKey('abstain')).toBe('vote.option.abstain');
    expect(optionKey('ja')).toBe('vote.option.yes');
    expect(optionKey('nein')).toBe('vote.option.no');
    expect(optionKey('enthaltung')).toBe('vote.option.abstain');
    expect(optionKey('vielleicht')).toBeNull();
  });

  it('sets noindex while the page lives and removes it after', () => {
    @Component({ standalone: true, template: '' })
    class Page {
      constructor() {
        useNoindex();
      }
    }
    const fixture = TestBed.createComponent(Page);
    const meta = TestBed.inject(Meta);
    expect(meta.getTag('name="robots"')?.content).toBe('noindex');
    fixture.destroy();
    expect(meta.getTag('name="robots"')).toBeNull();
  });

  describe('topParts', () => {
    const motion = (question: string | null, inText = true): PublicDecision => ({
      question,
      counts: { yes: 1 },
      result: 'passed',
      majorityRule: 'simple',
      secret: false,
      inText,
    });

    it('cuts the callout of a decision out of the text, with its tally and conditions', () => {
      const d = motion('Soll „A“ gefördert werden?');
      const md = 'Text.\n> [!abstimmung] **Soll „A“ gefördert werden?**\n> yes: 1, no: 0\n> Auflage 1: x\nWeiter.';
      expect(topParts(md, [d])).toEqual([
        { kind: 'text', markdown: 'Text.' },
        { kind: 'decision', decision: d },
        { kind: 'text', markdown: 'Weiter.' },
      ]);
    });

    it('matches an escaped question, the fallback head and a runoff round', () => {
      const plain = motion(null);
      const escaped = motion('Wahl *A*?');
      const runoff: PublicDecision = { ...motion('Vorsitz'), kind: 'election', round: 2 };
      const md = [
        '> [!abstimmung] **Beschlussfrage**',
        '',
        '> [!Abstimmung] **Wahl \\*A\\*?**',
        '',
        '> [!abstimmung] **Vorsitz (2. Wahlgang)**',
        '> Wahl · 1 Posten',
      ].join('\n');
      expect(topParts(md, [plain, escaped, runoff]).map((p) => p.kind)).toEqual([
        'decision',
        'decision',
        'decision',
      ]);
    });

    it('keeps a callout without a decision in the text, also one in a code fence', () => {
      const md = '> [!abstimmung] **Fremd**\n> yes: 1\n```\n> [!abstimmung] **Q**\n```';
      expect(topParts(md, [motion('Q'), motion('Fremd', false)])).toEqual([
        { kind: 'text', markdown: md },
      ]);
    });
  });
});
