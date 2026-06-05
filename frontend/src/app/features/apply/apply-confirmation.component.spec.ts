import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { ApplyConfirmationComponent } from './apply-confirmation.component';

describe('ApplyConfirmationComponent', () => {
  it('confirms receipt and shows the magic-link hint and reference id', async () => {
    await render(ApplyConfirmationComponent, {
      providers: [
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: { queryParamMap: of(convertToParamMap({ id: 'app-77' })) },
        },
      ],
    });
    expect(screen.getByText(/Antrag eingegangen/)).toBeInTheDocument();
    expect(screen.getByText(/persönlichen Link/)).toBeInTheDocument();
    expect(screen.getByText('app-77')).toBeInTheDocument();
  });
});
