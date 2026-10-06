import { render } from '@testing-library/angular';
import { QrCodeComponent, formatJoinCode, qrPath } from './qr-code.component';

describe('QrCodeComponent', () => {
  const qr = { size: 2, rows: ['10', '01'] };

  it('draws one unit square per dark module, moved by the quiet zone', () => {
    expect(qrPath(qr)).toBe('M4 4h1v1h-1zM5 5h1v1h-1z');
  });

  it('renders black modules on a white square with a label', async () => {
    const { container } = await render(QrCodeComponent, {
      inputs: { qr, label: 'QR-Code für die Sitzung' },
    });
    const svg = container.querySelector('svg')!;
    expect(svg.getAttribute('viewBox')).toBe('0 0 10 10');
    expect(svg.getAttribute('aria-label')).toBe('QR-Code für die Sitzung');
    expect(container.querySelector('rect')!.getAttribute('fill')).toBe('#fff');
    expect(container.querySelector('path')!.getAttribute('d')).toBe(qrPath(qr));
  });

  it('formats the join code in two groups', () => {
    expect(formatJoinCode('7KQ4MP')).toBe('7KQ-4MP');
    expect(formatJoinCode('ABC')).toBe('ABC');
    expect(formatJoinCode(null)).toBe('');
  });
});
