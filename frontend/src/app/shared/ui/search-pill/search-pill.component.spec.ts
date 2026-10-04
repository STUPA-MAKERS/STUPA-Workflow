import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { I18nService } from '@core/i18n/i18n.service';
import { runAxe } from '../../../../testing/a11y';
import { SearchPillComponent } from './search-pill.component';

@Component({
  standalone: true,
  imports: [SearchPillComponent],
  template: `
    <app-search-pill placeholder="132 Anträge durchsuchen" size="md" [(value)]="query">
      <button trail type="button" aria-label="Filter, 1 aktiv">F</button>
    </app-search-pill>
  `,
})
class FilterHostComponent {
  readonly query = signal('');
}

describe('SearchPillComponent', () => {
  describe('input mode', () => {
    it('is a named search box that writes back its value', async () => {
      const view = await render(FilterHostComponent);
      const box = screen.getByRole('searchbox', { name: '132 Anträge durchsuchen' });
      await userEvent.setup().type(box, 'Druck');
      expect(view.fixture.componentInstance.query()).toBe('Druck');
      expect(view.container.querySelector('app-search-pill')).toHaveClass('sp--md');
    });

    it('takes a value from outside', async () => {
      const view = await render(FilterHostComponent);
      view.fixture.componentInstance.query.set('Lastenrad');
      view.fixture.detectChanges();
      expect(screen.getByRole('searchbox')).toHaveValue('Lastenrad');
    });

    it('clears the value on Escape and leaves Escape alone when empty', async () => {
      const view = await render(FilterHostComponent);
      const user = userEvent.setup();
      const box = screen.getByRole('searchbox');
      await user.type(box, 'abc');
      await user.keyboard('{Escape}');
      expect(view.fixture.componentInstance.query()).toBe('');
      const outer = jest.fn();
      document.addEventListener('keydown', outer);
      await user.keyboard('{Escape}');
      await user.keyboard('x');
      expect(outer).toHaveBeenCalledTimes(2);
      document.removeEventListener('keydown', outer);
    });

    it('keeps the trailing control a separate button', async () => {
      const { container } = await render(FilterHostComponent);
      expect(screen.getByRole('button', { name: 'Filter, 1 aktiv' })).toBeInTheDocument();
      expect(container.querySelector('label button')).toBeNull();
      expect(await runAxe(container)).toHaveNoViolations();
    });

    it('takes a separate accessible name', async () => {
      await render(SearchPillComponent, {
        inputs: { placeholder: 'Suchen …', label: 'Sitzungen suchen' },
      });
      expect(screen.getByRole('searchbox', { name: 'Sitzungen suchen' })).toBeInTheDocument();
    });
  });

  describe('button mode', () => {
    it('is a button that emits activate and shows the shortcut', async () => {
      const activate = jest.fn();
      const { container } = await render(SearchPillComponent, {
        inputs: { mode: 'button', placeholder: 'Antrag, Sitzung, Seite …', shortcut: true },
        on: { activate },
      });
      const button = screen.getByRole('button', { name: 'Antrag, Sitzung, Seite …' });
      expect(button).toHaveAttribute('aria-keyshortcuts', 'Control+K');
      expect(container.querySelector('kbd')).toHaveTextContent('Strg+K');
      expect(container.querySelector('kbd')).toHaveAttribute('aria-hidden', 'true');
      expect(screen.queryByRole('searchbox')).toBeNull();
      await userEvent.setup().click(button);
      expect(activate).toHaveBeenCalledTimes(1);
      expect(await runAxe(container)).toHaveNoViolations();
    });

    it('names the key in the reader’s language', async () => {
      const view = await render(SearchPillComponent, {
        inputs: { mode: 'button', placeholder: 'Suchen', shortcut: true },
      });
      const i18n = TestBed.inject(I18nService);
      i18n.setLocale('en');
      view.fixture.detectChanges();
      expect(view.container.querySelector('kbd')).toHaveTextContent('Ctrl+K');
      i18n.setLocale('de');
    });

    it('uses the Command key on Apple hardware', async () => {
      const platform = jest.spyOn(navigator, 'platform', 'get').mockReturnValue('MacIntel');
      const { container } = await render(SearchPillComponent, {
        inputs: { mode: 'button', placeholder: 'Suchen', shortcut: true },
      });
      expect(screen.getByRole('button')).toHaveAttribute('aria-keyshortcuts', 'Meta+K');
      expect(container.querySelector('kbd')).toHaveTextContent('⌘K');
      platform.mockRestore();
    });

    it('has no hint and no shortcut without `shortcut`', async () => {
      const { container } = await render(SearchPillComponent, {
        inputs: { mode: 'button', placeholder: 'Suchen' },
      });
      expect(container.querySelector('kbd')).toBeNull();
      expect(screen.getByRole('button')).not.toHaveAttribute('aria-keyshortcuts');
    });
  });
});
