/**
 * The empty pane of the page "Veranstaltungen". The route loads this file and not the kit
 * entry itself, because a dynamic import of the whole entry keeps every export of it in
 * the start bundle.
 */
export { ListNoneComponent as EventNoneComponent } from '@stupa-makers/ui-kit/shell';
