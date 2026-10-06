import { de, en, type TranslationKey } from '@core/i18n/translations';
import { actorInfoFromLegacy, actorLabel, systemActorLabel, type Translate } from './actor-label.util';

const tDe: Translate = (key: TranslationKey) => de[key];
const tEn: Translate = (key: TranslationKey) => en[key] ?? de[key];

describe('actorLabel', () => {
  it('shows the name of a member', () => {
    expect(actorLabel({ kind: 'principal', displayName: 'Frederik Beimgraben' }, 'x', tDe)).toBe(
      'Frederik Beimgraben',
    );
  });

  it('shows the applicant label, or "Du" on the own status page', () => {
    expect(actorLabel({ kind: 'applicant' }, 'applicant', tDe)).toBe('Antragsteller:in');
    expect(
      actorLabel({ kind: 'applicant' }, 'applicant', tDe, { applicantKey: 'status.history.you' }),
    ).toBe('Du');
  });

  it.each([
    ['deadlines', 'System · Fristen', 'System · Deadlines'],
    ['flow', 'System · Ablauf', 'System · Workflow'],
    ['auto', 'System · Automatisch', 'System · Automatic'],
    ['confirmation', 'System · Bestätigung', 'System · Confirmation'],
    ['retention', 'System · Aufbewahrung', 'System · Retention'],
    ['migration', 'System · Migration', 'System · Migration'],
    ['unknown-key', 'System', 'System'],
  ])('labels the system key %s in DE and EN', (key, deLabel, enLabel) => {
    expect(actorLabel({ kind: 'system', key }, null, tDe)).toBe(deLabel);
    expect(actorLabel({ kind: 'system', key }, null, tEn)).toBe(enLabel);
  });

  it('shows the Gremium for the applicant view, with a fallback without a name', () => {
    expect(actorLabel({ kind: 'gremium', displayName: 'StuPa' }, 'StuPa', tDe)).toBe('StuPa');
    expect(actorLabel({ kind: 'gremium' }, null, tDe)).toBe('Gremium');
  });

  it('shows a neutral label for a deleted account', () => {
    expect(actorLabel({ kind: 'deleted' }, null, tDe)).toBe('Ehemaliges Konto');
    expect(actorLabel({ kind: 'deleted' }, null, tEn)).toBe('Former account');
    expect(actorLabel({ kind: 'principal', displayName: null }, null, tDe)).toBe('Ehemaliges Konto');
  });

  it('returns null without an actor', () => {
    expect(actorLabel(null, null, tDe)).toBeNull();
  });

  describe('legacy string without ActorInfo', () => {
    it.each([
      ['applicant', 'Antragsteller:in'],
      ['system:deadlines', 'System · Fristen'],
      ['system', 'System · Automatisch'],
      ['e03ad7d7-f039-40d1-b56d-7939b1628e46', 'Ehemaliges Konto'],
      ['2e70a4a288ae88e5765dafab2f423a4abde58ddb7903daab6b14e8ebf172520f', 'Ehemaliges Konto'],
      ['Mara Keller', 'Mara Keller'],
    ])('renders %s as %s', (legacy, label) => {
      expect(actorLabel(null, legacy, tDe)).toBe(label);
    });
  });

  it('never returns a raw key or id', () => {
    const raw = ['applicant', 'system:deadlines', 'system:flow', 'e03ad7d7-f039-40d1-b56d-7939b1628e46'];
    for (const value of raw) {
      expect(actorLabel(actorInfoFromLegacy(value), value, tDe)).not.toBe(value);
    }
  });

  it('has a DE and an EN label for every system key', () => {
    for (const key of ['auto', 'deadlines', 'flow', 'confirmation', 'retention', 'migration']) {
      expect(systemActorLabel(key, tDe)).toMatch(/^System · /);
      expect(systemActorLabel(key, (k) => en[k] ?? `MISSING ${k}`)).toMatch(/^System · /);
    }
  });
});
