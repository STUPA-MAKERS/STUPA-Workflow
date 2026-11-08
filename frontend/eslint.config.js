// @ts-check
const eslint = require('@eslint/js');
const tseslint = require('typescript-eslint');
const angular = require('@angular-eslint/eslint-plugin');
const angularTemplate = require('@angular-eslint/eslint-plugin-template');
const templateParser = require('@angular-eslint/template-parser');
const functionalPlugin = require('eslint-plugin-functional');

const functional = functionalPlugin.default ?? functionalPlugin;

module.exports = tseslint.config(
  {
    // `npm run e2e:tsc` checks the E2E Playwright tests separately. Those tests use
    // their own tsconfig at e2e/tsconfig.json, outside the Angular lint project.
    ignores: [
      'dist/**',
      'out-tsc/**',
      'coverage/**',
      'node_modules/**',
      '.angular/**',
      'e2e/**',
      // The UI-Kit library is a submodule with its own lint and CI setup.
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
    // Functional style (specs/style/shared/functional, 000438): warnings, not errors.
    // scripts/check_functional.py counts them per file against a baseline, so CI fails when
    // a file gets worse. Tests are an exception (000089) and stay out.
    files: ['src/**/*.ts'],
    ignores: ['**/*.spec.ts', 'src/testing/**'],
    plugins: { functional },
    rules: {
      'prefer-const': 'warn',
      'no-param-reassign': 'warn',
      '@typescript-eslint/switch-exhaustiveness-check': [
        'warn',
        { considerDefaultExhaustiveForUnions: true },
      ],
      'functional/no-let': 'warn',
      'functional/immutable-data': ['warn', { ignoreClasses: 'fieldsOnly' }],
      'functional/no-loop-statements': 'warn',
      'functional/prefer-readonly-type': [
        'warn',
        { allowLocalMutation: true, ignoreClass: true, ignoreInterface: false },
      ],
    },
  },
  {
    files: ['**/*.html'],
    languageOptions: { parser: templateParser },
    plugins: { '@angular-eslint/template': angularTemplate },
    rules: {
      '@angular-eslint/template/eqeqeq': 'error',
      '@angular-eslint/template/banana-in-box': 'error',
      // § NF/accessibility/conformance/000492: every accessibility rule as an error.
      ...angularTemplate.configs.accessibility.rules,
    },
  },
);
