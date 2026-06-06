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

  it('confirms receipt and shows the magic-link hint and reference id', async () => {
    await setup();
    expect(screen.getByText(/Antrag eingegangen/)).toBeInTheDocument();
    expect(screen.getByText(/persönlichen Link/)).toBeInTheDocument();
    expect(screen.getByText('app-77')).toBeInTheDocument();
  });

  it('renders the confirmation in English when the locale is EN', async () => {
    localStorage.setItem('ap.locale', 'en');
    await setup();
    expect(screen.getByText(/Application received/)).toBeInTheDocument();
    expect(screen.getByText(/personal link/)).toBeInTheDocument();
    expect(screen.queryByText(/Antrag eingegangen/)).not.toBeInTheDocument();
  });
});
