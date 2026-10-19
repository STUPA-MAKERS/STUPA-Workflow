import { HttpErrorResponse } from '@angular/common/http';
import { errorStatus, problemCode, problemDetail } from './problem';

describe('problem+json readers', () => {
  const http = new HttpErrorResponse({
    status: 409,
    error: { code: 'open_vote', detail: 'Eine Abstimmung ist offen.' },
  });

  it('reads code, detail and status of an HttpErrorResponse', () => {
    expect(problemCode(http)).toBe('open_vote');
    expect(problemDetail(http)).toBe('Eine Abstimmung ist offen.');
    expect(errorStatus(http)).toBe(409);
  });

  it('reads a plain object of the same shape', () => {
    expect(problemCode({ error: { code: 'x' } })).toBe('x');
    expect(problemDetail({ error: { detail: 'Zu wenig Budget' } })).toBe('Zu wenig Budget');
    expect(errorStatus({ status: '404' })).toBe(404);
  });

  it('gives the empty value for a missing or malformed field', () => {
    for (const err of [null, undefined, 'boom', 42, {}, { error: null }, { error: 'text' }]) {
      expect(problemCode(err)).toBe('');
      expect(problemDetail(err)).toBe('');
      expect(errorStatus(err)).toBe(0);
    }
    expect(problemCode({ error: { code: 7 } })).toBe('');
    expect(problemDetail({ error: { detail: { text: 'x' } } })).toBe('');
    expect(problemDetail({ error: {} })).toBe('');
    expect(problemDetail({ error: { detail: '' } })).toBe('');
    expect(errorStatus({ status: 'n/a' })).toBe(0);
  });
});
