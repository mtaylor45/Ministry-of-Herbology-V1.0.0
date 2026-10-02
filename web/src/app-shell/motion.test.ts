import { describe, expect, it } from 'vitest';
import { transitionKind } from './motion';

const id = '01890040-0000-7000-8000-000000000001';
const other = '01890040-0000-7000-8000-000000000002';

describe('which navigations turn a page', () => {
  it('turns between the facets of one plant', () => {
    expect(transitionKind(`/specimen/${id}/register`, `/specimen/${id}/tending`)).toBe('facet');
    expect(transitionKind(`/specimen/${id}/compendium`, `/specimen/${id}/journal`)).toBe('facet');
    expect(transitionKind(`/specimen/${id}`, `/specimen/${id}/tending`)).toBe('facet');
    expect(transitionKind(`/specimen/${id}/tending/`, `/specimen/${id}/register`)).toBe('facet');
  });

  it('does not turn to another plant', () => {
    expect(transitionKind(`/specimen/${id}/tending`, `/specimen/${other}/tending`)).toBeNull();
  });

  it('does not turn between sections, or into or out of a plant', () => {
    expect(transitionKind('/', '/almanac')).toBeNull();
    expect(transitionKind('/', `/specimen/${id}/tending`)).toBeNull();
    expect(transitionKind(`/specimen/${id}/tending`, '/')).toBeNull();
    expect(transitionKind(`/specimen/${id}/journal`, `/journal/${id}`)).toBeNull();
  });

  it('does not turn when nothing moved', () => {
    expect(transitionKind(`/specimen/${id}/tending`, `/specimen/${id}/tending`)).toBeNull();
    expect(transitionKind(null, `/specimen/${id}/tending`)).toBeNull();
    expect(transitionKind(`/specimen/${id}/tending`, undefined)).toBeNull();
  });
});
