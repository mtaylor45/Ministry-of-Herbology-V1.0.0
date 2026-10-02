/** Field primitives: a control is only usable if its label, hint and error
 *  are wired to it. That wiring is what these tests check. */

import { describe, expect, it } from 'vitest';
import NumberField from './NumberField.svelte';
import SearchInput from './SearchInput.svelte';
import SelectField from './SelectField.svelte';
import TextField from './TextField.svelte';
import Toggle from './Toggle.svelte';
import { describedBy } from './ids';
import { attrs, count, html, text } from './render';

/** The `for` on the label must name the control's id. */
function labelTarget(markup: string): string {
  return attrs(markup, 'label').for;
}

describe('TextField', () => {
  it('ties its label to its control', () => {
    const markup = html(TextField, { themed: 'What you call it', plain: 'Nickname' });
    expect(labelTarget(markup)).toBe(attrs(markup, 'input').id);
    expect(text(markup)).toContain('Nickname');
  });

  it('points at its hint through aria-describedby', () => {
    const markup = html(TextField, { plain: 'Nickname', hint: 'Only you see this.' });
    const described = attrs(markup, 'input')['aria-describedby'];
    expect(markup).toContain(`id="${described}"`);
    expect(text(markup)).toContain('Only you see this.');
  });

  it('marks an error on the control and says the word "Error"', () => {
    const markup = html(TextField, { plain: 'Species', error: 'No match in the accepted names.' });
    const input = attrs(markup, 'input');
    expect(input['aria-invalid']).toBe('true');
    expect(input['aria-describedby']).toBeTruthy();
    // Red is not enough: the error is named in words and carries an icon.
    expect(text(markup)).toContain('Error:');
  });

  it('marks required fields for assistive technology, not just with an asterisk', () => {
    const markup = html(TextField, { plain: 'Species', required: true });
    expect(attrs(markup, 'input')['aria-required']).toBe('true');
    expect(text(markup)).toContain('(required)');
  });

  it('becomes a textarea when rows are asked for', () => {
    const markup = html(TextField, { plain: 'Field note', rows: 3 });
    expect(count(markup, 'textarea')).toBe(1);
    expect(labelTarget(markup)).toBe(attrs(markup, 'textarea').id);
  });

  it('refuses a themed label with no plain one', () => {
    expect(() => html(TextField, { themed: 'What you call it' })).toThrow(/Field/);
  });
});

describe('NumberField', () => {
  it('asks for the numeric keypad and states its unit', () => {
    const markup = html(NumberField, { plain: 'Pot diameter', suffix: 'mm', min: 0, step: 10 });
    const input = attrs(markup, 'input');
    expect(input.type).toBe('number');
    expect(input.inputmode).toBe('decimal');
    expect(input.min).toBe('0');
    expect(input.step).toBe('10');
    // The unit is announced with the field, not left as decoration.
    expect(input['aria-describedby']).toBeTruthy();
    expect(text(markup)).toContain('mm');
  });
});

describe('SelectField', () => {
  it('leads each option with its plain meaning', () => {
    const markup = html(SelectField, {
      plain: 'Location',
      options: [
        { value: 'sill', themed: 'The kitchen sill', plain: 'Kitchen sill' },
        { value: 'bed', plain: 'South bed' },
      ],
    });
    expect(text(markup)).toContain('Kitchen sill (The kitchen sill)');
    expect(text(markup)).toContain('South bed');
    expect(labelTarget(markup)).toBe(attrs(markup, 'select').id);
  });
});

describe('Toggle', () => {
  it('is a switch with a state that is readable in words', () => {
    const on = html(Toggle, { plain: 'Notify me about this plant', checked: true });
    expect(attrs(on, 'button').role).toBe('switch');
    expect(attrs(on, 'button')['aria-checked']).toBe('true');
    expect(text(on)).toContain('On');

    const off = html(Toggle, { plain: 'Notify me about this plant', checked: false });
    expect(attrs(off, 'button')['aria-checked']).toBe('false');
    expect(text(off)).toContain('Off');
  });

  it('names itself through aria-labelledby rather than a bare switch', () => {
    const markup = html(Toggle, { plain: 'Notify me about this plant' });
    const labelledBy = attrs(markup, 'button')['aria-labelledby'];
    expect(markup).toContain(`id="${labelledBy}"`);
  });
});

describe('SearchInput', () => {
  it('is a search landmark with a labelled control', () => {
    const markup = html(SearchInput, { themed: 'Consult the Register', plain: 'Search specimens' });
    expect(attrs(markup, 'form').role).toBe('search');
    expect(attrs(markup, 'input').type).toBe('search');
    expect(labelTarget(markup)).toBe(attrs(markup, 'input').id);
  });

  it('keeps the label for screen readers when it is hidden', () => {
    const markup = html(SearchInput, { plain: 'Search specimens', hideLabel: true });
    expect(markup).toContain('visually-hidden');
    expect(text(markup)).toContain('Search specimens');
  });

  it('offers a named clear control once there is something to clear', () => {
    expect(text(html(SearchInput, { plain: 'Search', value: '' }))).not.toContain('Clear');
    const filled = html(SearchInput, { plain: 'Search', value: 'basil' });
    expect(text(filled)).toContain('Clear the search');
  });
});

describe('describedBy', () => {
  it('joins the ids that exist and disappears when none do', () => {
    expect(describedBy('a', undefined, 'b')).toBe('a b');
    expect(describedBy(undefined, false, null)).toBeUndefined();
  });
});
