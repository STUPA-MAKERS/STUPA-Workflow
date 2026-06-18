import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import type { DataDiff } from '@core/api/models';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { BadgeComponent } from '@shared/ui/badge/badge.component';

/**
 * Feld-Diff-Renderer (added/removed/changed) — geteilt zwischen Antrags-Historie
 * (Submission-Versionen) und Config-Versionen (Forms/Flow/Branding, #config-versioning).
 * Reine Präsentation: nimmt einen aufgelösten {@link DataDiff} (Arrays) und rendert
 * je Eintrag ein Severity-Badge + Feld-Key + Alt→Neu-Werte.
 */
@Component({
  selector: 'app-config-diff',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, BadgeComponent],
  templateUrl: './config-diff.component.html',
  styleUrl: './config-diff.component.scss',
})
export class ConfigDiffComponent {
  /** Aufgelöster Diff (`null`/leer ⇒ »keine Änderungen«). */
  readonly diff = input<DataDiff | null>(null);

  protected isEmpty(d: DataDiff | null): boolean {
    return !d || (d.added.length === 0 && d.removed.length === 0 && d.changed.length === 0);
  }

  /** Wert lesbar machen (Objekte als JSON; null/undefined als »—«). */
  protected fmt(value: unknown): string {
    if (value === null || value === undefined) return '—';
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
  }
}
