/**
 * The shared building blocks of the app (`@shared/ui`).
 *
 * The ui-kit (`@stupa-makers/ui-kit`) holds the generic controls: buttons, fields, tables,
 * dialogs. These blocks are specific to this app; they use its i18n and its status
 * model. Import them from here:
 *
 *   import { ListItemComponent, StatusTextComponent } from '@shared/ui';
 *
 * Exception: code in the initial bundle (the shell, the layout, the command palette)
 * imports a block by its path, for example `@shared/ui/avatar/avatar.component`. When the
 * initial bundle imports this barrel, every block that a lazy page uses goes into the
 * initial bundle too.
 */
export { AvatarComponent, AvatarStackComponent, initials } from './avatar/avatar.component';
export type { AvatarSize } from './avatar/avatar.component';
export { DateBlockComponent } from './date-block/date-block.component';
export { EmptyStateComponent } from './empty-state/empty-state.component';
export { FieldGroupComponent, FieldRowComponent } from './field-group/field-group.component';
export { FileDropZoneComponent, acceptsFile } from './file-drop-zone/file-drop-zone.component';
export { HistoryComponent } from './history/history.component';
export type { HistoryEntry } from './history/history.component';
export {
  LIST_DETAIL_SPLIT_MIN,
  ListDetailLayoutComponent,
  NAV_RAIL_WIDTH,
} from './list-detail/list-detail-layout.component';
export { ListItemComponent } from './list-item/list-item.component';
export { NoteComponent } from './note/note.component';
export type { NoteKind } from './note/note.component';
export { PageHeaderComponent } from './page-header/page-header.component';
export { RowMenuComponent } from './row-menu/row-menu.component';
export type { RowMenuItem, RowMenuSection } from './row-menu/row-menu.component';
export { SearchPillComponent } from './search-pill/search-pill.component';
export type { SearchPillMode } from './search-pill/search-pill.component';
export { SegBarComponent } from './seg-bar/seg-bar.component';
export type { Seg, SegBarSize, SegTone } from './seg-bar/seg-bar.component';
export { SelectionBarComponent } from './selection-bar/selection-bar.component';
export { SideSheetComponent } from './side-sheet/side-sheet.component';
export type { SheetSide } from './side-sheet/side-sheet.component';
export { SkeletonComponent } from './skeleton/skeleton.component';
export type { SkeletonVariant } from './skeleton/skeleton.component';
export { StatusTextComponent } from './status-text/status-text.component';
export * from '../status-kind.util';
