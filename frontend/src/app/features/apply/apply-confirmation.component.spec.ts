import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { ApplyConfirmationComponent } from './apply-confirmation.component';

describe('ApplyConfirmationComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  async function setup() {
    return render(ApplyConfirmationComponent, {
      providers: [
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: { queryParamMap: of(convertToParamMap({ id: 'app-77' })) },
        },
      ],
    });
  }

  it('asks to confirm the email, shows the 12h-discard note and reference id', async () => {
    await setup();
    expect(screen.getByText(/E-Mail bestätigen/)).toBeInTheDocument();
    expect(screen.getByText(/persönlichen Link/)).toBeInTheDocument();
    expect(screen.getByText(/nach 12 Stunden automatisch verworfen/)).toBeInTheDocument();
    expect(screen.getByText('app-77')).toBeInTheDocument();
  });

  it('renders the confirmation in English when the locale is EN', async () => {
    localStorage.setItem('ap.locale', 'en');
    await setup();
    expect(screen.getByText(/confirm your email/)).toBeInTheDocument();
    expect(screen.getByText(/personal link/)).toBeInTheDocument();
    expect(screen.getByText(/discarded after 12 hours/)).toBeInTheDocument();
    expect(screen.queryByText(/E-Mail bestätigen/)).not.toBeInTheDocument();
  });
});
