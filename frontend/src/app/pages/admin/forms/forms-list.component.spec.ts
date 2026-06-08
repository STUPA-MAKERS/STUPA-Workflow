import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AdminApiService } from '../admin-api.service';
import type { ApplicationTypeCreateBody, ApplicationTypeFull } from '../admin.models';
import { FormsListComponent } from './forms-list.component';

function type(id: string, de: string): ApplicationTypeFull {
  return { id, name: { de, en: de }, gremiumId: 'g1', hasBudget: false, activeFormVersionId: null };
}

async function setup() {
  const createApplicationType = jest.fn((b: ApplicationTypeCreateBody) =>
    of({ id: 'f-new', name: b.name, gremiumId: null, hasBudget: false, activeFormVersionId: null }),
  );
  const api = {
    listApplicationTypesFull: jest.fn(() => of([type('f1', 'Förderantrag')])),
    listGremien: jest.fn(() => of([{ id: 'g1', name: 'StuPa' }])),
    createApplicationType,
  };
  const view = await render(FormsListComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      provideRouter([{ path: 'admin/forms/:id', children: [] }]),
    ],
  });
  return { ...view, createApplicationType };
}

describe('FormsListComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists application types', async () => {
    await setup();
    expect(screen.getByRole('link', { name: 'Förderantrag' })).toBeInTheDocument();
  });

  it('creates a type via the dialog with an auto key', async () => {
    const { createApplicationType } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Formular anlegen' }));

    const nameDe = screen.getByLabelText('Titel (DE)');
    await userEvent.type(nameDe, 'Härtefall Antrag');

    const add = screen.getAllByRole('button', { name: 'Formular anlegen' });
    // the dialog footer add button is the enabled one
    await userEvent.click(add[add.length - 1]);

    expect(createApplicationType).toHaveBeenCalledTimes(1);
    const body = createApplicationType.mock.calls[0][0];
    expect(body.key).toBe('haertefall-antrag');
    expect(body.name).toEqual({ de: 'Härtefall Antrag', en: '' });
  });
});
