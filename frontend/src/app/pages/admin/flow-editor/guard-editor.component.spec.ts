import { render } from '@testing-library/angular';
import type { SelectOption } from '@shared/ui';
import type { Guard } from '../admin.models';
import { GuardEditorComponent } from './guard-editor.component';

const ROLES: SelectOption[] = [{ value: 'stupa', label: 'StuPa' }];
const GREMIEN: SelectOption[] = [{ value: 'g1', label: 'Finanzausschuss' }];

/** Renders ONCE; `setGuard`/`setAutomatic` mutate inputs in place (controlled
 *  component) so a single test can walk several guard shapes without re-rendering
 *  (re-rendering would re-configure the TestBed, which Angular forbids per test). */
async function setup(
  initial: { guard?: Guard | null; automatic?: boolean } = {},
) {
  const emitted: (Guard | null)[] = [];
  const view = await render(GuardEditorComponent, {
    inputs: {
      guard: initial.guard ?? null,
      automatic: initial.automatic ?? false,
      roleOptions: ROLES,
      gremiumOptions: GREMIEN,
    },
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  c.guardChange.subscribe((g: Guard | null) => emitted.push(g));
  const setGuard = (g: Guard | null): void => {
    view.fixture.componentRef.setInput('guard', g);
    view.fixture.detectChanges();
  };
  const setAutomatic = (a: boolean): void => {
    view.fixture.componentRef.setInput('automatic', a);
    view.fixture.detectChanges();
  };
  return {
    ...view,
    c,
    emitted,
    setGuard,
    setAutomatic,
    last: () => emitted[emitted.length - 1],
  };
}

describe('GuardEditorComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  describe('computed views over the guard input', () => {
    it('reports none/leaf/combinator kinds and op', async () => {
      const { c, setGuard } = await setup({ guard: null });
      expect(c.op()).toBe('');
      expect(c.kind()).toBe('none');
      expect(c.children()).toEqual([]);
      expect(c.valueKind()).toBe('none');
      expect(c.strValue()).toBe('');

      setGuard({ roleIs: 'stupa' });
      expect(c.op()).toBe('roleIs');
      expect(c.kind()).toBe('leaf');
      expect(c.valueKind()).toBe('role');
      expect(c.strValue()).toBe('stupa');

      setGuard({ and: [{ roleIs: 'a' }, { deadlinePassed: true }] });
      expect(c.op()).toBe('and');
      expect(c.kind()).toBe('combinator');
      expect(c.children()).toHaveLength(2);
    });

    it('children() is empty for a combinator whose value is not an array', async () => {
      const { c } = await setup({ guard: { not: { deadlinePassed: true } } as Guard });
      expect(c.kind()).toBe('combinator');
      expect(c.children()).toEqual([]);
    });

    it('strValue() blanks object/null values', async () => {
      const { c, setGuard } = await setup({ guard: { compare: { field: 'x', op: '==', value: '' } } });
      expect(c.strValue()).toBe('');
      setGuard({ deadlinePassed: null } as unknown as Guard);
      expect(c.strValue()).toBe('');
      setGuard({ deadlinePassed: true });
      expect(c.strValue()).toBe('true');
    });

    it('valueKind() resolves every operator family', async () => {
      const { c, setGuard } = await setup({ guard: null });
      const cases: Array<[Guard, string]> = [
        [{ deadlinePassed: true }, 'none'],
        [{ budgetFitsApplication: true }, 'none'],
        [{ actorIsApplicant: true }, 'none'],
        [{ roleIs: 'a' }, 'role'],
        [{ applicantRoleIs: 'a' }, 'role'],
        [{ isInCommittee: 'g' }, 'committee'],
        [{ applicantCommitteeIs: 'g' }, 'committee'],
        [{ compare: { field: 'f', op: '==', value: '' } }, 'compare'],
        [{ hasField: 'iban' }, 'text'],
        [{ budgetIs: 'b1' }, 'text'],
      ];
      for (const [guard, expected] of cases) {
        setGuard(guard);
        expect(c.valueKind()).toBe(expected);
      }
    });

    it('cmp() parses a compare spec and falls back to defaults', async () => {
      const { c, setGuard } = await setup({ guard: { compare: { field: 'amount', op: '>', value: 100 } } });
      expect(c.cmp()).toEqual({ field: 'amount', op: '>', value: '100' });

      setGuard({ compare: {} } as Guard);
      expect(c.cmp()).toEqual({ field: '', op: '==', value: '' });

      setGuard({ compare: 'x' } as Guard);
      expect(c.cmp()).toEqual({ field: '', op: '==', value: '' });

      setGuard(null);
      expect(c.cmp()).toEqual({ field: '', op: '==', value: '' });
    });
  });

  describe('opOptions()', () => {
    it('omits actor operators on automatic transitions, includes them otherwise', async () => {
      const { c, setAutomatic } = await setup({ automatic: true });
      const autoOps = c.opOptions().map((o: SelectOption) => o.value);
      expect(autoOps).toContain('and');
      expect(autoOps).toContain('deadlinePassed');
      expect(autoOps).not.toContain('roleIs');
      expect(autoOps).not.toContain('isInCommittee');

      setAutomatic(false);
      const manualOps = c.opOptions().map((o: SelectOption) => o.value);
      expect(manualOps).toContain('roleIs');
      expect(manualOps).toContain('isInCommittee');
    });
  });

  describe('onOpChange()', () => {
    it('emits null when the operator is cleared', async () => {
      const { c, last } = await setup({ guard: { roleIs: 'a' } });
      c.onOpChange('');
      expect(last()).toBeNull();
    });

    it('and/or seed from existing children', async () => {
      const { c, last } = await setup({ guard: { or: [{ roleIs: 'a' }] } });
      c.onOpChange('and');
      expect(last()).toEqual({ and: [{ roleIs: 'a' }] });
    });

    it('and/or seed from the current leaf when not already a combinator', async () => {
      const { c, last } = await setup({ guard: { roleIs: 'a' } });
      c.onOpChange('or');
      expect(last()).toEqual({ or: [{ roleIs: 'a' }] });
    });

    it('and/or seed empty when there is no guard', async () => {
      const { c, last } = await setup({ guard: null });
      c.onOpChange('and');
      expect(last()).toEqual({ and: [] });
    });

    it('not reuses the existing first child', async () => {
      const { c, last } = await setup({ guard: { and: [{ roleIs: 'a' }, { hasField: 'x' }] } });
      c.onOpChange('not');
      expect(last()).toEqual({ not: [{ roleIs: 'a' }] });
    });

    it('not falls back to the current guard (no children present)', async () => {
      const { c, last } = await setup({ guard: { roleIs: 'a' } });
      c.onOpChange('not');
      expect(last()).toEqual({ not: [{ roleIs: 'a' }] });
    });

    it('not falls back to a default compare leaf with no guard', async () => {
      const { c, last } = await setup({ guard: null });
      c.onOpChange('not');
      expect(last()).toEqual({ not: [{ compare: { field: '', op: '==', value: '' } }] });
    });

    it('switching to a leaf op emits the right default value', async () => {
      const { c, last, setGuard } = await setup({ guard: null });
      c.onOpChange('roleIs');
      expect(last()).toEqual({ roleIs: '' });

      setGuard(null);
      c.onOpChange('deadlinePassed');
      expect(last()).toEqual({ deadlinePassed: true });

      c.onOpChange('budgetFitsApplication');
      expect(last()).toEqual({ budgetFitsApplication: true });

      c.onOpChange('actorIsApplicant');
      expect(last()).toEqual({ actorIsApplicant: true });

      c.onOpChange('compare');
      expect(last()).toEqual({ compare: { field: '', op: '==', value: '' } });
    });
  });

  describe('addChild / removeChild', () => {
    it('addChild appends a default compare leaf for and/or only', async () => {
      const { c, last } = await setup({ guard: { and: [{ roleIs: 'a' }] } });
      c.addChild();
      expect(last()).toEqual({
        and: [{ roleIs: 'a' }, { compare: { field: '', op: '==', value: '' } }],
      });
    });

    it('addChild is a no-op for non-and/or operators', async () => {
      const { c, emitted } = await setup({ guard: { not: [{ roleIs: 'a' }] } as Guard });
      c.addChild();
      expect(emitted).toHaveLength(0);
    });

    it('removeChild drops by index, collapsing to null when empty', async () => {
      const { c, last } = await setup({ guard: { and: [{ roleIs: 'a' }, { hasField: 'x' }] } });
      c.removeChild(0);
      expect(last()).toEqual({ and: [{ hasField: 'x' }] });
    });

    it('removeChild collapses to null when the last child goes', async () => {
      const { c, last } = await setup({ guard: { or: [{ roleIs: 'a' }] } });
      c.removeChild(0);
      expect(last()).toBeNull();
    });

    it('removeChild is a no-op for non-and/or operators', async () => {
      const { c, emitted } = await setup({ guard: { roleIs: 'a' } });
      c.removeChild(0);
      expect(emitted).toHaveLength(0);
    });
  });

  describe('setChild', () => {
    it('replaces a child in an and/or list', async () => {
      const { c, last } = await setup({ guard: { and: [{ roleIs: 'a' }, { hasField: 'x' }] } });
      c.setChild(1, { roleIs: 'b' });
      expect(last()).toEqual({ and: [{ roleIs: 'a' }, { roleIs: 'b' }] });
    });

    it('drops a child set to null', async () => {
      const { c, last } = await setup({ guard: { or: [{ roleIs: 'a' }, { hasField: 'x' }] } });
      c.setChild(0, null);
      expect(last()).toEqual({ or: [{ hasField: 'x' }] });
    });

    it('collapses to null when the only child is set to null', async () => {
      const { c, last } = await setup({ guard: { and: [{ roleIs: 'a' }] } });
      c.setChild(0, null);
      expect(last()).toBeNull();
    });

    it('rewraps the (first) child for not', async () => {
      const { c, last } = await setup({ guard: { not: [{ roleIs: 'a' }] } as Guard });
      c.setChild(0, { hasField: 'x' });
      expect(last()).toEqual({ not: [{ hasField: 'x' }] });
    });

    it('collapses not to null when its only child is set to null', async () => {
      const { c, last } = await setup({ guard: { not: [{ roleIs: 'a' }] } as Guard });
      c.setChild(0, null);
      expect(last()).toBeNull();
    });

    it('is a no-op for leaf operators', async () => {
      const { c, emitted } = await setup({ guard: { roleIs: 'a' } });
      c.setChild(0, { hasField: 'y' });
      expect(emitted).toHaveLength(0);
    });
  });

  describe('setValue / setCompare', () => {
    it('setValue rewrites the single-operand guard', async () => {
      const { c, last } = await setup({ guard: { roleIs: 'a' } });
      c.setValue('stupa');
      expect(last()).toEqual({ roleIs: 'stupa' });
    });

    it('setValue is a no-op when there is no operator', async () => {
      const { c, emitted } = await setup({ guard: null });
      c.setValue('x');
      expect(emitted).toHaveLength(0);
    });

    it('setCompare merges a patch into the current compare spec', async () => {
      const { c, last } = await setup({
        guard: { compare: { field: 'amount', op: '==', value: '0' } },
      });
      c.setCompare({ op: '>' });
      expect(last()).toEqual({ compare: { field: 'amount', op: '>', value: '0' } });
      c.setCompare({ field: 'total', value: '5' });
      expect(last()).toEqual({ compare: { field: 'total', op: '==', value: '5' } });
    });
  });
});
