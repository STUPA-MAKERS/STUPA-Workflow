/** Jest config — Angular standalone via jest-preset-angular (ESM-aware). */
module.exports = {
  preset: 'jest-preset-angular',
  setupFilesAfterEnv: ['<rootDir>/setup-jest.ts'],
  testEnvironment: 'jsdom',
  roots: ['<rootDir>/src'],
  testMatch: ['**/*.spec.ts'],
  moduleNameMapper: {
    '^@core/(.*)$': '<rootDir>/src/app/core/$1',
    '^@shared/(.*)$': '<rootDir>/src/app/shared/$1',
    '\\.(css|scss)$': '<rootDir>/src/testing/style-mock.js',
  },
  transform: {
    '^.+\\.(ts|mjs|js|html)$': [
      'jest-preset-angular',
      {
        tsconfig: '<rootDir>/tsconfig.spec.json',
        stringifyContentPathRegex: '\\.(html|svg)$',
      },
    ],
  },
  transformIgnorePatterns: ['node_modules/(?!.*\\.mjs$|@angular|rxjs|@ngx-formly)'],
  collectCoverageFrom: [
    'src/app/**/*.ts',
    '!src/app/**/*.spec.ts',
    '!src/app/**/index.ts',
    // Bootstrap-/Wiring-Dateien (Composition Root) — über Build/E2E abgedeckt.
    '!src/app/app.config.ts',
    '!src/app/app.routes.ts',
  ],
  // Specs decken jetzt nahezu den gesamten App-Code ab (stmts 99.7 / branches 98.2 /
  // funcs 99.3 / lines 99.9). Schwellen knapp unter den Ist-Stand geratscht — echte
  // Regressionen brechen den Build, marginale Schwankungen nicht. Halten/anheben.
  coverageThreshold: {
    global: { statements: 98, branches: 96, functions: 98, lines: 99 },
  },
};
