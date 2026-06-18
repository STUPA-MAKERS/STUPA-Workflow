import { render } from '@testing-library/angular';
import type { DataDiff } from '@core/api/models';
import { ConfigDiffComponent } from './config-diff.component';

describe('ConfigDiffComponent', () => {
  it('renders a row per changed/added/removed field', async () => {
    const diff: DataDiff = {
      added: [{ key: 'field:new', value: 'X' }],
      removed: [{ key: 'field:old', value: 'Y' }],
      changed: [{ key: 'field:edit', old: 'A', new: 'B' }],
    };
    const { container } = await render(ConfigDiffComponent, { inputs: { diff } });
    const items = container.querySelectorAll('.cfg-diff li');
    expect(items.length).toBe(3);
    expect(container.textContent).toContain('field:edit');
    expect(container.textContent).toContain('field:new');
    expect(container.textContent).toContain('field:old');
  });

  it('shows the no-changes hint for a null diff', async () => {
    const { container } = await render(ConfigDiffComponent, { inputs: { diff: null } });
    expect(container.querySelector('.cfg-diff')).toBeNull();
    expect(container.querySelector('.cfg-diff__none')).not.toBeNull();
  });

  it('shows the no-changes hint for an all-empty diff', async () => {
    const diff: DataDiff = { added: [], removed: [], changed: [] };
    const { container } = await render(ConfigDiffComponent, { inputs: { diff } });
    expect(container.querySelector('.cfg-diff')).toBeNull();
    expect(container.querySelector('.cfg-diff__none')).not.toBeNull();
  });

  it('JSON-encodes object values and dashes null', async () => {
    const diff: DataDiff = {
      added: [{ key: 'k', value: { a: 1 } }],
      removed: [{ key: 'r', value: null }],
      changed: [],
    };
    const { container } = await render(ConfigDiffComponent, { inputs: { diff } });
    expect(container.textContent).toContain('{"a":1}');
    expect(container.textContent).toContain('—');
  });
});
