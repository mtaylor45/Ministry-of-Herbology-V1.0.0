/** Shared shapes the components take. Types live here rather than in a
 *  component file because a Svelte instance script cannot export them. */

import type { Paired } from './pairing';

/** One option in a select. Plain text is required; themed is a garnish. */
export interface SelectOption extends Paired {
  value: string;
  disabled?: boolean;
}
