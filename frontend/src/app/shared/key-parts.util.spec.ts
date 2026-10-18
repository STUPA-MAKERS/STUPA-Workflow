import { keyParts } from './key-parts.util';

describe('keyParts', () => {
  it('splits after each dot and underscore, and keeps them', () => {
    expect(keyParts('application.force_status')).toEqual(['application.', 'force_', 'status']);
  });

  it('keeps a key without a boundary whole', () => {
    expect(keyParts('admin')).toEqual(['admin']);
  });
});
