/**
 * Test helpers for the app's select field (`app-select`, `SelectFieldComponent`).
 *
 * The field is a combobox button that opens the option list after one task. A spec that
 * used `userEvent.selectOptions` on a native `<select>` opens the field and clicks the
 * option instead.
 */
import { within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';

/** Let the list of an opened field render. */
export async function settleList(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve));
}

/** Open the select field and wait for its listbox. */
export async function openSelect(field: HTMLElement): Promise<HTMLElement> {
  if (field.getAttribute('aria-expanded') !== 'true') await userEvent.click(field);
  await settleList();
  const id = field.getAttribute('aria-controls');
  const list = id ? document.getElementById(id) : null;
  if (!list) throw new Error('The select field did not open its list.');
  return list;
}

/** Open the select field and choose the option with this accessible name. */
export async function pickOption(field: HTMLElement, option: string | RegExp): Promise<void> {
  const list = await openSelect(field);
  await userEvent.click(within(list).getByRole('option', { name: option }));
}

/**
 * The option labels of a select field, in order, without the initials of an avatar in
 * front of them. Opens the list and closes it again.
 */
export async function optionLabels(field: HTMLElement): Promise<string[]> {
  const list = await openSelect(field);
  const labels = within(list)
    .getAllByRole('option')
    .map((o) => (o.querySelector('.sel__label') ?? o).textContent?.trim() ?? '');
  await userEvent.click(field);
  return labels;
}

/** The select field with this accessible name. */
export function selectField(name: string | RegExp, root: HTMLElement = document.body): HTMLElement {
  return within(root).getByRole('combobox', { name });
}

