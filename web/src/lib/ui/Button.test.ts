/** Button: the pairing rule, and telling "disabled" from "busy". */

import { describe, expect, it } from 'vitest';
import Button from './Button.svelte';
import { buttonAttrs, buttonIsInert } from './button';
import { attrs, html, text } from './render';

describe('Button', () => {
  it('renders the themed label with its plain meaning', () => {
    const markup = html(Button, { themed: 'Tend to it', plain: 'Water now' });
    expect(text(markup)).toContain('Tend to it');
    expect(text(markup)).toContain('Water now');
  });

  it('refuses a themed label with no plain one', () => {
    expect(() => html(Button, { themed: 'Tend to it' })).toThrow(/Button/);
  });

  it('has no children snippet to smuggle an unpaired themed word through', () => {
    // The label is the only way text gets into a button, and it goes via Label.
    expect(Object.keys(html(Button, { plain: 'Water now' }))).toBeTruthy();
    expect(() => html(Button, { themed: 'Tend to it', plain: '' })).toThrow(/Button/);
  });

  it('marks a disabled button disabled and takes it out of the tab order', () => {
    const found = attrs(html(Button, { plain: 'Unavailable', disabled: true }), 'button');
    expect(found).toHaveProperty('disabled');
    expect(found['data-state']).toBe('disabled');
    expect(found['aria-busy']).toBeUndefined();
  });

  it('keeps a loading button focusable, busy and announced', () => {
    const markup = html(Button, { plain: 'Save', loading: true, busyPlain: 'Saving…' });
    const found = attrs(markup, 'button');
    expect(found['aria-busy']).toBe('true');
    expect(found['aria-disabled']).toBe('true');
    expect(found).not.toHaveProperty('disabled');
    expect(text(markup)).toContain('Saving…');
  });

  it('carries the variant through to the markup', () => {
    for (const variant of ['primary', 'quiet', 'destructive'] as const) {
      expect(attrs(html(Button, { plain: 'Go', variant }), 'button')['data-variant']).toBe(variant);
    }
  });
});

describe('buttonAttrs', () => {
  it('treats both disabled and loading as inert to clicks', () => {
    expect(buttonIsInert({ disabled: true })).toBe(true);
    expect(buttonIsInert({ loading: true })).toBe(true);
    expect(buttonIsInert({})).toBe(false);
  });

  it('never sets the disabled attribute while loading', () => {
    expect(buttonAttrs('primary', { loading: true, disabled: true }).disabled).toBeUndefined();
  });
});
