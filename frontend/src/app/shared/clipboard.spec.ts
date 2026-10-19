import { copyToClipboard } from './clipboard';

describe('copyToClipboard', () => {
  const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
  afterEach(() => {
    if (original) Object.defineProperty(navigator, 'clipboard', original);
    else delete (navigator as { clipboard?: unknown }).clipboard;
  });
  const setClip = (value: unknown) =>
    Object.defineProperty(navigator, 'clipboard', { value, configurable: true });

  it('writes the text and resolves true', async () => {
    const writeText = jest.fn(() => Promise.resolve());
    setClip({ writeText });
    await expect(copyToClipboard('https://x/a')).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith('https://x/a');
  });

  it('resolves false when the write fails', async () => {
    setClip({ writeText: () => Promise.reject(new Error('denied')) });
    await expect(copyToClipboard('x')).resolves.toBe(false);
  });

  it('resolves false without a clipboard', async () => {
    setClip(undefined);
    await expect(copyToClipboard('x')).resolves.toBe(false);
  });
});
