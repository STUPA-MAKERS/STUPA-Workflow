import { TestBed } from '@angular/core/testing';
import { render, screen } from '@testing-library/angular';
import { runAxe } from '../../../testing/a11y';
import { FileOpenHostComponent } from './file-open-host.component';
import { FileOpenService } from './file-open.service';

describe('FileOpenHostComponent', () => {
  it('§F/administration/files/001080: shows the opened file with its download link, without axe violations', async () => {
    const { container, fixture } = await render(FileOpenHostComponent);
    TestBed.inject(FileOpenService).open({ name: 'Foto.jpg', url: '/api/f/1/file', mime: 'image/jpeg' });
    fixture.detectChanges();
    const link = screen.getAllByRole('link').find((a) => a.getAttribute('href') === '/api/f/1/file');
    expect(link).toBeTruthy();
    expect(link?.hasAttribute('download')).toBe(true);
    expect(await runAxe(container.ownerDocument.body)).toHaveNoViolations();
  });
});
