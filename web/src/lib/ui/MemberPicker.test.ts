/** MemberPicker: who is acting, remembered per device, never required to be. */

import { describe, expect, it } from 'vitest';
import MemberPicker from './MemberPicker.svelte';
import {
  MEMBER_STORAGE_KEY,
  initialMember,
  memberById,
  readRememberedMember,
  rememberMember,
  roleLabel,
  type Member,
} from './member';
import { html, text } from './render';

const MEMBERS: Member[] = [
  { id: 'm-1', name: 'Keeper', role: 'keeper' },
  { id: 'm-2', name: 'Tender', role: 'tender' },
  { id: 'm-3', name: 'Observer', role: 'observer' },
];

describe('the picker', () => {
  it('is a radio group with a paired legend', () => {
    const markup = html(MemberPicker, { members: MEMBERS });
    expect(markup).toContain('<fieldset');
    expect(markup).toContain('<legend');
    expect(text(markup)).toContain('Whose hands');
    expect(text(markup)).toContain('Acting as');
    expect(markup.match(/type="radio"/g)).toHaveLength(3);
  });

  it('shows each member with their name and their role, in both halves', () => {
    const shown = text(html(MemberPicker, { members: MEMBERS }));
    for (const member of MEMBERS) expect(shown).toContain(member.name);
    expect(shown).toContain('Runs the household');
    expect(shown).toContain('Waters and tends');
    expect(shown).toContain('Looks, does not touch');
  });

  it('marks the chosen one in words, not only in colour', () => {
    const markup = html(MemberPicker, { members: MEMBERS, value: 'm-2' });
    expect(markup).toContain('data-selected="true"');
    expect(text(markup)).toContain('Acting as Tender.');
    expect(markup.match(/checked/g)).toHaveLength(1);
  });

  it('says so when nobody is chosen', () => {
    expect(text(html(MemberPicker, { members: MEMBERS }))).toContain('Nobody chosen yet.');
  });

  it('says so when the household has nobody on record', () => {
    const markup = html(MemberPicker, { members: [] });
    expect(markup).not.toContain('type="radio"');
    expect(text(markup)).toContain('no members on record');
  });

  it('shows a role the contract does not name as itself', () => {
    const shown = text(
      html(MemberPicker, { members: [{ id: 'x', name: 'Guest', role: 'guest' }] }),
    );
    expect(shown).toContain('guest');
    expect(roleLabel('guest')).toEqual({ plain: 'guest' });
  });

  it('takes its own labels, paired', () => {
    const shown = text(
      html(MemberPicker, { members: MEMBERS, themed: 'Whose eyes', plain: 'Who saw it' }),
    );
    expect(shown).toContain('Whose eyes');
    expect(shown).toContain('Who saw it');
  });

  it('carries a hint the group is described by', () => {
    const markup = html(MemberPicker, { members: MEMBERS, hint: 'Recorded against this person.' });
    const hintId = /aria-describedby="([^"]+)"/.exec(markup)?.[1];
    expect(hintId).toBeTruthy();
    expect(markup).toContain(`id="${hintId}"`);
  });
});

/** A `localStorage` the tests own. */
function fakeStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    data,
  };
}

describe('remembering', () => {
  it('uses the key Morning Rounds has used so nobody loses their choice', () => {
    expect(MEMBER_STORAGE_KEY).toBe('moh:last-member');
  });

  it('reads and writes the id', () => {
    const store = fakeStorage();
    rememberMember('m-2', store);
    expect(store.data.get(MEMBER_STORAGE_KEY)).toBe('m-2');
    expect(readRememberedMember(store)).toBe('m-2');
  });

  it('works with storage blocked — a convenience, not state', () => {
    const blocked = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
    };
    expect(readRememberedMember(blocked)).toBeNull();
    expect(() => rememberMember('m-1', blocked)).not.toThrow();
    expect(readRememberedMember(null)).toBeNull();
    expect(() => rememberMember('m-1', null)).not.toThrow();
  });

  it('starts on the remembered member only while they are still in the household', () => {
    expect(initialMember(MEMBERS, 'm-3')).toBe('m-3');
    expect(initialMember(MEMBERS, 'gone')).toBe('');
    expect(initialMember(MEMBERS, null)).toBe('');
  });

  it('starts on nobody by default, and on the first only when asked', () => {
    // A default that names a person who did not do the thing is a wrong record.
    expect(initialMember(MEMBERS, null)).toBe('');
    expect(initialMember(MEMBERS, null, true)).toBe('m-1');
    expect(initialMember([], null, true)).toBe('');
  });

  it('finds a member by id', () => {
    expect(memberById(MEMBERS, 'm-2')?.name).toBe('Tender');
    expect(memberById(MEMBERS, 'nope')).toBeNull();
  });
});
