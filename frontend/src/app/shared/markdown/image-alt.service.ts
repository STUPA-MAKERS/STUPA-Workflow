import {
  ApplicationRef,
  EnvironmentInjector,
  Injectable,
  createComponent,
  inject,
} from '@angular/core';
import { DOCUMENT } from '@angular/common';
import { ImageAltDialogComponent } from './image-alt-dialog.component';

/**
 * Opens the alt text dialog for one image file and resolves to the text: a description,
 * `''` for a decorative image, or `null` when the user cancels (app spec 000506). The
 * dialog lives on `<body>`, so a textarea directive and a sheet can ask the same way.
 */
@Injectable({ providedIn: 'root' })
export class ImageAltService {
  private readonly appRef = inject(ApplicationRef);
  private readonly injector = inject(EnvironmentInjector);
  private readonly doc = inject(DOCUMENT);

  ask(file: File): Promise<string | null> {
    return new Promise((resolve) => {
      const ref = createComponent(ImageAltDialogComponent, { environmentInjector: this.injector });
      ref.setInput('fileName', file.name);
      ref.instance.done.subscribe((alt) => {
        this.appRef.detachView(ref.hostView);
        ref.destroy();
        resolve(alt);
      });
      this.appRef.attachView(ref.hostView);
      this.doc.body.appendChild(ref.location.nativeElement as HTMLElement);
      ref.changeDetectorRef.detectChanges();
    });
  }

  /** Ask for each file in turn. A cancelled file is left out. */
  async askAll(files: readonly File[]): Promise<readonly { file: File; alt: string }[]> {
    return files.reduce<Promise<readonly { file: File; alt: string }[]>>(async (acc, file) => {
      const done = await acc;
      const alt = await this.ask(file);
      return alt === null ? done : [...done, { file, alt }];
    }, Promise.resolve([]));
  }
}
