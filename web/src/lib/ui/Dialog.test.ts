/** Dialog: named, modal, dismissible on purpose — and focus that is trapped
 *  while it is open and handed back when it closes. */

import { describe, expect, it } from 'vitest';
import Dialog from './Dialog.svelte';
import { focusTrap, focusable, resolveTrapTarget } from './focusTrap';
import { html, text } from './render';

const body = () => {};

describe('Dialog', () => {
  it('renders nothing at all when it is closed', () => {
    expect(text(html(Dialog, { plain: 'Remove this plant', open: false, children: body }))).toBe(
      '',
    );
  });

  it('is a modal dialog named by its own title', () => {
    const markup = html(Dialog, {
      themed: 'Uproot this specimen?',
      plain: 'Remove this plant',
      open: true,
      children: body,
    });
    expect(markup).toContain('role="dialog"');
    expect(markup).toContain('aria-modal="true"');
    const labelledBy = /aria-labelledby="([^"]+)"/.exec(markup)?.[1];
    expect(labelledBy).toBeTruthy();
    expect(markup).toContain(`id="${labelledBy}"`);
    expect(text(markup)).toContain('Remove this plant');
  });

  it('describes itself when given a description, and points at it', () => {
    const markup = html(Dialog, {
      plain: 'Remove this plant',
      description: 'Its logs and photos go with it.',
      open: true,
      children: body,
    });
    const describedBy = /aria-describedby="([^"]+)"/.exec(markup)?.[1];
    expect(markup).toContain(`id="${describedBy}"`);
  });

  it('gives its close control a plain name rather than a bare cross', () => {
    const markup = html(Dialog, { plain: 'Remove this plant', open: true, children: body });
    expect(text(markup)).toContain('Close');
  });

  it('leaves out the close control when the question must be answered', () => {
    const markup = html(Dialog, {
      plain: 'Remove this plant',
      open: true,
      dismissible: false,
      children: body,
    });
    expect(text(markup)).not.toContain('Close');
    expect(markup).toContain('data-dismissible="false"');
  });

  it('refuses a themed title with no plain one', () => {
    expect(() =>
      html(Dialog, { themed: 'Uproot this specimen?', open: true, children: body }),
    ).toThrow(/Dialog/);
  });
});

/** Stand-ins for DOM nodes: the trap's decisions do not need a browser. */
function stub(name: string, extra: Record<string, unknown> = {}) {
  return {
    name,
    focused: 0,
    getAttribute: (key: string) => (extra[key] as string) ?? null,
    focus() {
      this.focused += 1;
    },
    ...extra,
  };
}

describe('focus trap', () => {
  const first = stub('first');
  const middle = stub('middle');
  const last = stub('last');
  const items = [first, middle, last];

  it('wraps forward from the last element to the first', () => {
    expect(resolveTrapTarget({ key: 'Tab' }, items, last)).toBe(first);
  });

  it('wraps backward from the first element to the last', () => {
    expect(resolveTrapTarget({ key: 'Tab', shiftKey: true }, items, first)).toBe(last);
  });

  it('lets the browser handle a Tab in the middle', () => {
    expect(resolveTrapTarget({ key: 'Tab' }, items, middle)).toBeNull();
  });

  it('pulls focus in when it is somewhere outside the dialog', () => {
    expect(resolveTrapTarget({ key: 'Tab' }, items, null)).toBe(first);
    expect(resolveTrapTarget({ key: 'Tab', shiftKey: true }, items, null)).toBe(last);
  });

  it('ignores keys that are not Tab, so Escape and Enter reach the dialog', () => {
    expect(resolveTrapTarget({ key: 'Escape' }, items, first)).toBeNull();
    expect(resolveTrapTarget({ key: 'Enter' }, items, first)).toBeNull();
  });

  it('does nothing when a dialog has nothing focusable in it', () => {
    expect(resolveTrapTarget({ key: 'Tab' }, [], null)).toBeNull();
  });

  it('skips candidates that are present but cannot take focus', () => {
    const hidden = stub('hidden', { hidden: true });
    const ariaHidden = stub('aria-hidden', { 'aria-hidden': 'true' });
    const inert = stub('inert', { inert: '' });
    const kept = focusable([first, hidden, ariaHidden, inert, last]);
    expect(kept.map((item) => item.name)).toEqual(['first', 'last']);
  });

  it('is exported as an action for components to use', () => {
    expect(typeof focusTrap).toBe('function');
  });
});
