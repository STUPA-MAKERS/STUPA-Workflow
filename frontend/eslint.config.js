// @ts-check
const eslint = require('@eslint/js');
const tseslint = require('typescript-eslint');
const angular = require('@angular-eslint/eslint-plugin');
const angularTemplate = require('@angular-eslint/eslint-plugin-template');
const templateParser = require('@angular-eslint/template-parser');

module.exports = tseslint.config(
  {
    // E2E (Playwright) wird separat per `npm run e2e:tsc` geprüft — eigener
    // tsconfig (e2e/tsconfig.json), nicht Teil des Angular-Lint-Projekts.
    ignores: [
      'dist/**',
      'out-tsc/**',
      'coverage/**',
      'node_modules/**',
      '.angular/**',
      'e2e/**',
      // UI-Kit-Library als Submodule — hat eigenes Lint-/CI-Setup, nicht Teil des App-Lints.
      'vendor/**',
      'playwright.config.ts',
      'playwright-report/**',
      'test-results/**',
    ],
  },
  {
    files: ['**/*.ts'],
    extends: [eslint.configs.recommended, ...tseslint.configs.recommended],
    plugins: { '@angular-eslint': angular },
    languageOptions: {
      parserOptions: { project: ['tsconfig.app.json', 'tsconfig.spec.json'] },
    },
    rules: {
      '@angular-eslint/directive-selector': [
        'error',
        { type: 'attribute', prefix: 'app', style: 'camelCase' },
      ],
      '@angular-eslint/component-selector': [
        'error',
        { type: 'element', prefix: 'app', style: 'kebab-case' },
      ],
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/explicit-function-return-type': 'off',
    },
  },
  {
    files: ['**/*.html'],
    languageOptions: { parser: templateParser },
    plugins: { '@angular-eslint/template': angularTemplate },
    rules: {
      '@angular-eslint/template/eqeqeq': 'error',
      '@angular-eslint/template/banana-in-box': 'error',
    },
  },
);
