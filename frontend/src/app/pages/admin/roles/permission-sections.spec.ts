import { permissionSections } from './permission-sections';

describe('permissionSections', () => {
  it('groups the catalogue by prefix, in display order, and keeps the catalogue order', () => {
    const out = permissionSections([
      'audit.read',
      'application.read',
      'budget.view',
      'form.configure',
      'meeting.view_all',
      'application.share',
      'mcp.use',
      'webhook.manage',
    ]);
    expect(out.map((s) => s.key)).toEqual(['applications', 'budget', 'meetings', 'admin', 'security']);
    expect(out[0].keys).toEqual(['application.read', 'application.share']);
    expect(out[3].keys).toEqual(['form.configure', 'webhook.manage']);
    expect(out[4].keys).toEqual(['audit.read', 'mcp.use']);
    expect(out[0].title).toBe('admin.roles.section.applications');
  });

  it('puts an unknown prefix into "Weitere" and leaves out empty sections', () => {
    const out = permissionSections(['zzz.new', 'budget.book']);
    expect(out.map((s) => s.key)).toEqual(['budget', 'other']);
    expect(out[1].keys).toEqual(['zzz.new']);
  });

  it('gives nothing for an empty catalogue', () => {
    expect(permissionSections([])).toEqual([]);
  });
});
