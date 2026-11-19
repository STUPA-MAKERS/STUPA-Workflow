import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { Uuid } from '@core/api/models';
import { TodosApiService } from '@core/api/todos.service';
import { AuthService } from '@core/auth/auth.service';
import { applicationReads } from './application-reads';

/** The reads ahead of an application detail: the transitions only with the right to fire them. */
describe('applicationReads', () => {
  const ID = 'a-1' as Uuid;

  function setup(canTransition: boolean) {
    const api = {
      getApplication: jest.fn(() => of({})),
      applicationForm: jest.fn(() => of({})),
      versions: jest.fn(() => of([])),
      comments: jest.fn(() => of([])),
      timeline: jest.fn(() => of([])),
      applicationLinks: jest.fn(() => of([])),
      transitions: jest.fn(() => of([])),
      listAttachments: jest.fn(() => of([])),
    };
    const todos = { linked: jest.fn(() => of([])) };
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiClient, useValue: api },
        { provide: TodosApiService, useValue: todos },
        { provide: AuthService, useValue: { can: jest.fn(() => canTransition) } },
      ],
    });
    const reads = TestBed.runInInjectionContext(() => applicationReads(ID));
    return { api, todos, reads };
  }

  it('reads the transitions for a person who fires them', () => {
    const { api, todos, reads } = setup(true);
    expect(reads).toHaveLength(9);
    expect(api.transitions).toHaveBeenCalledWith(ID, { detail: true });
    expect(api.getApplication).toHaveBeenCalledWith(ID, { quiet: true, detail: true });
    expect(todos.linked).toHaveBeenCalledWith('application', ID);
  });

  it('leaves the transitions out for a person who does not fire them', () => {
    const { api, reads } = setup(false);
    expect(reads).toHaveLength(8);
    expect(api.transitions).not.toHaveBeenCalled();
  });
});
