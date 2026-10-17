/**
 * The EN catalog is a lazy chunk. `setup-jest.ts` registers it for every other spec, so
 * these tests load a fresh copy of the module to see the state before the first load.
 */
type Module = typeof import('./translations');

function fresh(): Module {
  let mod!: Module;
  jest.isolateModules(() => {
    mod = jest.requireActual<Module>('./translations');
  });
  return mod;
}

describe('loadCatalog', () => {
  afterEach(() => jest.dontMock('./translations.en'));

  it('starts with DE only and fills EN from its chunk', async () => {
    const mod = fresh();
    expect(mod.isCatalogLoaded('de')).toBe(true);
    expect(mod.isCatalogLoaded('en')).toBe(false);
    expect(mod.CATALOG.en['action.login']).toBeUndefined();

    await mod.loadCatalog('en');

    expect(mod.isCatalogLoaded('en')).toBe(true);
    expect(mod.CATALOG.en['action.login']).toBe('Sign in');
  });

  it('resolves at once for a loaded locale', async () => {
    const mod = fresh();
    await expect(mod.loadCatalog('de')).resolves.toBeUndefined();
    expect(mod.CATALOG.de['action.login']).toBe('Anmelden');
  });

  it('rejects and keeps the catalog when the chunk does not load', async () => {
    jest.doMock('./translations.en', () => {
      throw new Error('offline');
    });
    const mod = fresh();
    await expect(mod.loadCatalog('en')).rejects.toThrow('offline');
    expect(mod.isCatalogLoaded('en')).toBe(false);
    expect(mod.CATALOG.en).toEqual({});
  });
});
