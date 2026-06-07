import { CapitalizePipe } from './capitalize.pipe';

describe('CapitalizePipe', () => {
  const pipe = new CapitalizePipe();

  it('capitalizes a single word', () => {
    expect(pipe.transform('member')).toBe('Member');
  });

  it('capitalizes each word across whitespace, hyphen and underscore', () => {
    expect(pipe.transform('vote manager')).toBe('Vote Manager');
    expect(pipe.transform('vote-manager')).toBe('Vote-Manager');
    expect(pipe.transform('stupa_admin')).toBe('Stupa_Admin');
  });

  it('leaves the rest of each word untouched (value-preserving display only)', () => {
    expect(pipe.transform('aStA')).toBe('AStA');
  });

  it('returns an empty string for nullish input', () => {
    expect(pipe.transform('')).toBe('');
    expect(pipe.transform(null)).toBe('');
    expect(pipe.transform(undefined)).toBe('');
  });
});
