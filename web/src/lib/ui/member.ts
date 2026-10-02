/** Who is acting. The design system, an earlier release.
 *
 * one shared sign-in, and the household member is picked at the
 * moment of the act — completing a task, approving a plate, writing a field
 * note — so the record still says who. The last choice is remembered **per
 * browser**, because it is a convenience about this device and not a fact
 * about the household: a phone that one person carries can default to them,
 * and a tablet on the kitchen wall should ask.
 *
 * `localStorage` is the right place for that and the wrong thing to depend
 * on: private browsing and blocked storage both make it throw, and a picker
 * that cannot remember must still pick. Every read and write below swallows
 * the failure.
 */

import type { Paired } from './pairing';

/** `Member` from the contract. `role` is one of three words today; it is left
 *  open so a fourth does not break the picker. */
export interface Member {
  id: string;
  name: string;
  role: 'keeper' | 'tender' | 'observer' | string;
}

/** Same key Morning Rounds has used so adopting the picker keeps
 *  everybody's remembered choice. */
export const MEMBER_STORAGE_KEY = 'moh:last-member';

/** What a role is, in a word a stranger to the app understands. The themed
 *  half is the role as the Ministry would style it; both are shown. */
export const ROLE_LABELS: Record<string, Paired> = {
  keeper: { themed: 'Keeper', plain: 'Runs the household' },
  tender: { themed: 'Tender', plain: 'Waters and tends' },
  observer: { themed: 'Observer', plain: 'Looks, does not touch' },
};

/** A role the contract does not name is shown as itself, plainly. */
export function roleLabel(role: string): Paired {
  return ROLE_LABELS[role] ?? { plain: role };
}

type Storage = Pick<globalThis.Storage, 'getItem' | 'setItem'>;

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    // Some browsers throw on the mere mention of it when storage is blocked.
    return null;
  }
}

/** The member id remembered on this device, or null. Never throws. */
export function readRememberedMember(
  store: Storage | null = storage(),
  key: string = MEMBER_STORAGE_KEY,
): string | null {
  try {
    return store?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

/** Remember a choice on this device. Never throws; a choice that cannot be
 *  stored is still the choice for this page. */
export function rememberMember(
  id: string,
  store: Storage | null = storage(),
  key: string = MEMBER_STORAGE_KEY,
): void {
  try {
    store?.setItem(key, id);
  } catch {
    // private mode, quota, blocked: not worth a crash
  }
}

/** The member to start on: the remembered one if they are still in the
 *  household, else nobody. Nobody, not the first: a default that names a
 *  person who did not do the thing is a wrong record, and the whole point of
 *  the picker is that the record says who. A screen that would rather start
 *  on somebody passes `fallbackToFirst`. */
export function initialMember(
  members: readonly Member[],
  remembered: string | null,
  fallbackToFirst = false,
): string {
  if (remembered && members.some((member) => member.id === remembered)) return remembered;
  return fallbackToFirst ? (members[0]?.id ?? '') : '';
}

export function memberById(members: readonly Member[], id: string): Member | null {
  return members.find((member) => member.id === id) ?? null;
}
