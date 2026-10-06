import { render, screen } from '@testing-library/angular';
import { de } from '@core/i18n/translations';
import { AdminHomeComponent } from './admin-home.component';

describe('AdminHomeComponent', () => {
  it('shows the empty sheet of a list/detail page, no gremien list', async () => {
    await render(AdminHomeComponent);
    expect(screen.getByText(de['admin.home.none'])).toBeInTheDocument();
    expect(screen.getByText(de['admin.home.noneBody'])).toBeInTheDocument();
    expect(screen.queryByRole('list')).toBeNull();
  });
});
