/** The most-used control in the app: one-tap and batch task completion. */

import { describe, expect, it } from 'vitest';
import TaskCheckbox from './TaskCheckbox.svelte';
import {
  CHECKED_PLAIN,
  nextSelectAll,
  selectionState,
  selectionSummary,
  toggleAll,
  toggleOne,
} from './selection';
import { attrs, count, html, text } from './render';

describe('TaskCheckbox', () => {
  it('is a real checkbox with the plain label attached', () => {
    const markup = html(TaskCheckbox, { themed: 'The basil thirsts', plain: 'Water the basil' });
    expect(attrs(markup, 'input').type).toBe('checkbox');
    expect(text(markup)).toContain('Water the basil');
  });

  it('is one tap target, not a label plus a separate control', () => {
    const markup = html(TaskCheckbox, { plain: 'Water the basil' });
    expect(count(markup, 'label')).toBe(1);
    expect(count(markup, 'input')).toBe(1);
  });

  it('says "done" in words as well as in colour once it is complete', () => {
    const markup = html(TaskCheckbox, { plain: 'Water the basil', checked: true });
    expect(attrs(markup, 'input')).toHaveProperty('checked');
    expect(text(markup)).toContain('Done');
  });

  it('carries the batch select-all half-state through the server render', () => {
    const markup = html(TaskCheckbox, { plain: 'Select all', checkState: 'mixed' });
    expect(attrs(markup, 'input')['aria-checked']).toBe('mixed');
    expect(attrs(markup, 'label')['data-state']).toBe('mixed');
  });

  it('describes the row with its plain meta line rather than a bare tick', () => {
    const markup = html(TaskCheckbox, {
      plain: 'Water the basil',
      meta: 'Kitchen sill — due today',
    });
    const described = attrs(markup, 'input')['aria-describedby'];
    expect(described).toBeTruthy();
    expect(markup).toContain(`id="${described}"`);
  });

  it('disables the input rather than only dimming the row', () => {
    const markup = html(TaskCheckbox, { plain: 'Water the basil', disabled: true });
    expect(attrs(markup, 'input')).toHaveProperty('disabled');
  });

  it('says "done" by default, because a tick usually is the completion', () => {
    const markup = html(TaskCheckbox, { plain: 'Water the basil', checked: true });
    expect(attrs(markup, 'label')['data-meaning']).toBe('completion');
    expect(text(markup)).toContain('Done');
  });

  it('says "selected" and does not call it done when a tick only gathers a row', () => {
    // Morning Rounds: attribution is chosen at completion, so a tick
    // cannot be the completion. J worked around the word from outside and could
    // not reach the strike-through; `meaning` moves both, together.
    const markup = html(TaskCheckbox, {
      plain: 'Water the basil',
      meaning: 'selection',
      checked: true,
    });
    expect(attrs(markup, 'label')['data-meaning']).toBe('selection');
    expect(text(markup)).toContain('Selected');
    expect(text(markup)).not.toContain('Done');
  });

  it('carries the meaning on the element the strike-through keys off', () => {
    // The strike-through is `[data-meaning='completion'][data-state='checked']`.
    // Without the attribute on the same element, a selected row reads as
    // finished however the word beside it is worded.
    const selected = attrs(
      html(TaskCheckbox, { plain: 'x', meaning: 'selection', checked: true }),
      'label',
    );
    expect(selected['data-meaning']).toBe('selection');
    expect(selected['data-state']).toBe('checked');
  });

  it('still lets a list supply its own word for a ticked row', () => {
    const markup = html(TaskCheckbox, {
      plain: 'Select every task due',
      meaning: 'selection',
      checked: true,
      donePlain: 'All selected',
    });
    expect(text(markup)).toContain('All selected');
  });

  it('refuses a themed task name with no plain one', () => {
    expect(() => html(TaskCheckbox, { themed: 'The basil thirsts' })).toThrow(/TaskCheckbox/);
  });
});

describe('batch selection', () => {
  it('shows none, some and all as three distinct states', () => {
    expect(selectionState(0, 3)).toBe('unchecked');
    expect(selectionState(2, 3)).toBe('mixed');
    expect(selectionState(3, 3)).toBe('checked');
    expect(selectionState(0, 0)).toBe('unchecked');
  });

  it('selects everything from any state short of all, and clears from all', () => {
    expect(nextSelectAll('unchecked')).toBe(true);
    expect(nextSelectAll('mixed')).toBe(true);
    expect(nextSelectAll('checked')).toBe(false);
    expect(toggleAll(['a', 'b'], 'mixed')).toEqual(new Set(['a', 'b']));
    expect(toggleAll(['a', 'b'], 'checked')).toEqual(new Set());
  });

  it('toggles one row without mutating the selection it was given', () => {
    const before = new Set(['a']);
    expect(toggleOne(before, 'b')).toEqual(new Set(['a', 'b']));
    expect(toggleOne(before, 'a')).toEqual(new Set());
    expect(before).toEqual(new Set(['a']));
  });

  it('has a plain word for each meaning of a tick, never a colour alone', () => {
    expect(CHECKED_PLAIN.completion).toBe('Done');
    expect(CHECKED_PLAIN.selection).toBe('Selected');
  });

  it('summarises a selection in plain words', () => {
    expect(selectionSummary(0, 3)).toBe('Nothing selected of 3');
    expect(selectionSummary(2, 3)).toBe('2 of 3 selected');
  });
});
