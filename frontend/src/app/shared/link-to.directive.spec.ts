import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { LinkToDirective, isExternalUrl } from './link-to.directive';

@Component({
  imports: [LinkToDirective],
  template: `<a [appLinkTo]="url">x</a>`,
})
class HostComponent {
  url = '/meetings/m-1?item=a-1';
}

function setup(url: string) {
  TestBed.configureTestingModule({ imports: [HostComponent], providers: [provideRouter([])] });
  const fixture = TestBed.createComponent(HostComponent);
  fixture.componentInstance.url = url;
  fixture.detectChanges();
  const go = jest.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
  const a = fixture.nativeElement.querySelector('a') as HTMLAnchorElement;
  return { a, go };
}

describe('LinkToDirective', () => {
  it('tells an address that leaves the app', () => {
    expect(isExternalUrl('https://paperless.example/documents/7/details')).toBe(true);
    expect(isExternalUrl('/todos?card=c-1')).toBe(false);
    expect(isExternalUrl(null)).toBe(false);
  });

  it('opens an app address through the router', () => {
    const { a, go } = setup('/meetings/m-1?item=a-1');
    expect(a.getAttribute('href')).toBe('/meetings/m-1?item=a-1');
    expect(a.getAttribute('target')).toBeNull();
    const click = new MouseEvent('click', { bubbles: true, cancelable: true });
    a.dispatchEvent(click);
    expect(click.defaultPrevented).toBe(true);
    expect(go).toHaveBeenCalledWith('/meetings/m-1?item=a-1');
  });

  it('leaves a click with a modifier key to the browser', () => {
    const { a, go } = setup('/meetings/m-1');
    const click = new MouseEvent('click', { bubbles: true, cancelable: true, ctrlKey: true });
    a.dispatchEvent(click);
    expect(click.defaultPrevented).toBe(false);
    expect(go).not.toHaveBeenCalled();
  });

  it('opens an address that leaves the app in a new tab', () => {
    const { a, go } = setup('https://paperless.example/documents/7/details');
    expect(a.getAttribute('href')).toBe('https://paperless.example/documents/7/details');
    expect(a.getAttribute('target')).toBe('_blank');
    expect(a.getAttribute('rel')).toBe('noopener');
    a.addEventListener('click', (event) => event.preventDefault());
    a.click();
    expect(go).not.toHaveBeenCalled();
  });
});
