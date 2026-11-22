import { Injector, type Provider, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { ToastService } from '@stupa-makers/ui-kit';
import { PROTOCOL_API, type ProtocolApi } from '@stupa-makers/ui-kit/views/protocol';
import { ImageAltService } from '@shared/markdown/image-alt.service';
import { imageUploadErrorKey } from '@shared/markdown/markdown-image-upload.directive';
import { MediaApiService } from '@shared/markdown/media-api.service';
import { KnownNamesService } from './known-names.service';

/** The i18n key of a PDF upload error, from the HTTP status of the problem response. */
export function documentUploadErrorKey(status?: number): TranslationKey {
  switch (status) {
    case 403:
      return 'markdown.document.error.forbidden';
    case 413:
      return 'markdown.document.error.tooLarge';
    case 415:
      return 'markdown.document.error.type';
    case 429:
      return 'markdown.image.error.rate';
    case 503:
      return 'markdown.image.error.storage';
    default:
      return 'markdown.document.error.upload';
  }
}

/**
 * The `PROTOCOL_API` port of the TOP sheet over the media store of the app. The alt text
 * dialog is the app's (app spec 000506), and an upload error shows as a toast. The services
 * resolve on the first call, so a sheet that never uploads needs no HTTP client.
 */
export function appProtocolApi(injector: Injector): ProtocolApi {
  const toast = (key: TranslationKey): void => {
    injector.get(ToastService).show(injector.get(I18nService).translate(key), 'error');
  };
  const status = (err: unknown): number | undefined => (err as { status?: number } | null)?.status;
  return {
    imageAlts: (files) => injector.get(ImageAltService).askAll(files),
    uploadImage: async (file) => {
      try {
        const image = await firstValueFrom(injector.get(MediaApiService).uploadImage(file));
        return `/api/media/images/${image.id}`;
      } catch (err) {
        toast(imageUploadErrorKey(status(err)));
        throw err;
      }
    },
    uploadDocument: async (meetingId, file) => {
      try {
        const doc = await firstValueFrom(injector.get(MediaApiService).uploadDocument(meetingId, file));
        return { name: doc.name, src: doc.url };
      } catch (err) {
        toast(documentUploadErrorKey(status(err)));
        throw err;
      }
    },
    documentInfo: (src) =>
      firstValueFrom(injector.get(MediaApiService).documentInfo(src)).then((info) => info.pages),
    knownNames: (meetingId) => injector.get(KnownNamesService).names(meetingId),
  };
}

/** Provide the port for the TOP sheet. */
export function provideProtocolApi(): Provider {
  return { provide: PROTOCOL_API, useFactory: () => appProtocolApi(inject(Injector)) };
}
