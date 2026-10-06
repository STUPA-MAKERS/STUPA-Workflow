import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import type { QrMatrix } from '@core/api/models';

/** The quiet zone around the code, in modules (ISO/IEC 18004 asks for four). */
export const QR_QUIET_ZONE = 4;

/**
 * Build one SVG path for the dark modules of a QR matrix: one unit square per module,
 * moved by the quiet zone. The server computes the matrix (segno); the client only draws it.
 */
export function qrPath(qr: QrMatrix): string {
  const parts: string[] = [];
  qr.rows.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      if (row[x] === '1') parts.push(`M${x + QR_QUIET_ZONE} ${y + QR_QUIET_ZONE}h1v1h-1z`);
    }
  });
  return parts.join('');
}

/** "7KQ4MP" → "7KQ-4MP": the join code in two groups, easier to read aloud and to type. */
export function formatJoinCode(code: string | null | undefined): string {
  if (!code) return '';
  return code.length === 6 ? `${code.slice(0, 3)}-${code.slice(3)}` : code;
}

/**
 * A QR code as inline SVG. The modules are black on white in both themes, because a
 * scanner needs the contrast: the white quiet zone is part of the image. The size comes
 * from the host (`width`), the image scales without blur.
 */
@Component({
  selector: 'app-qr-code',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg
      class="qr"
      [attr.viewBox]="viewBox()"
      role="img"
      [attr.aria-label]="label()"
      shape-rendering="crispEdges"
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect [attr.width]="side()" [attr.height]="side()" fill="#fff" />
      <path [attr.d]="path()" fill="#000" />
    </svg>
  `,
  styles: `
    :host {
      display: block;
      line-height: 0;
    }
    .qr {
      display: block;
      width: 100%;
      height: auto;
    }
  `,
})
export class QrCodeComponent {
  readonly qr = input.required<QrMatrix>();
  /** What the code holds, for a screen reader ("QR-Code für …"). */
  readonly label = input('');

  protected readonly side = computed(() => this.qr().size + 2 * QR_QUIET_ZONE);
  protected readonly viewBox = computed(() => `0 0 ${this.side()} ${this.side()}`);
  protected readonly path = computed(() => qrPath(this.qr()));
}
