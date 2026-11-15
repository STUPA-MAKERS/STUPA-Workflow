import { TestBed } from '@angular/core/testing';
import { Subject, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { KnownName } from '@stupa-makers/ui-kit/markdown-editor';
import { KnownNamesService } from './known-names.service';

describe('KnownNamesService (000970)', () => {
  it('loads the names of a meeting once and gives them when they are there', () => {
    const answer = new Subject<readonly KnownName[]>();
    const getKnownNames = jest.fn(() => answer);
    TestBed.configureTestingModule({ providers: [{ provide: ApiClient, useValue: { getKnownNames } }] });
    const service = TestBed.inject(KnownNamesService);
    expect(service.names('m-1')).toEqual([]);
    expect(service.names('m-1')).toEqual([]);
    expect(getKnownNames).toHaveBeenCalledTimes(1);
    answer.next([{ first: 'Lena', last: 'Hoffmann' }]);
    expect(service.names('m-1')).toEqual([{ first: 'Lena', last: 'Hoffmann' }]);
  });

  it('loads again after an error', () => {
    const getKnownNames = jest.fn(() => throwError(() => new Error('down')));
    TestBed.configureTestingModule({ providers: [{ provide: ApiClient, useValue: { getKnownNames } }] });
    const service = TestBed.inject(KnownNamesService);
    expect(service.names('m-1')).toEqual([]);
    expect(service.names('m-1')).toEqual([]);
    expect(getKnownNames).toHaveBeenCalledTimes(2);
  });
});
