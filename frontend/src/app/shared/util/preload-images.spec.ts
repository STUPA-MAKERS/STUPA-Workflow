import { preloadImages } from './preload-images';

interface FakeImage {
  src: string;
  fire: (type: 'load' | 'error') => void;
}

/** A fake image: records its src, and the test fires load or error by hand. */
function fakes() {
  const made: FakeImage[] = [];
  const make = () => {
    const listeners = new Map<string, () => void>();
    const fake: FakeImage = { src: '', fire: (type) => listeners.get(type)?.() };
    made.push(fake);
    return {
      addEventListener: (type: string, fn: () => void) => listeners.set(type, fn),
      setAttribute: (_name: string, value: string) => (fake.src = value),
    } as unknown as HTMLImageElement;
  };
  return { made, make };
}

describe('preloadImages', () => {
  afterEach(() => jest.useRealTimers());

  it('§NF/performance/loading/001280: resolves at once without a URL', async () => {
    const { made, make } = fakes();
    await expect(preloadImages(['', ''], 3000, make)).resolves.toBeUndefined();
    expect(made).toHaveLength(0);
  });

  it('§NF/performance/loading/001280: waits for each image, once per URL, and counts a failed one as done', async () => {
    const { made, make } = fakes();
    let done = false;
    const p = preloadImages(['/a', '/b', '/a'], 3000, make).then(() => (done = true));
    expect(made.map((i) => i.src)).toEqual(['/a', '/b']);
    made[0].fire('load');
    await Promise.resolve();
    expect(done).toBe(false);
    made[1].fire('error');
    await p;
    expect(done).toBe(true);
  });

  it('§NF/performance/loading/001280: resolves after the limit when an image never answers', async () => {
    jest.useFakeTimers();
    const { make } = fakes();
    let done = false;
    void preloadImages(['/slow'], 3000, make).then(() => (done = true));
    jest.advanceTimersByTime(2999);
    await Promise.resolve();
    expect(done).toBe(false);
    jest.advanceTimersByTime(1);
    await Promise.resolve();
    expect(done).toBe(true);
  });
});
