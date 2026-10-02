/** One plain fact in a description list. A Svelte instance script cannot export
 *  a type, so the shape `FactList` takes lives here. */
export interface Fact {
  /** The plain-language term. Required: it is what a screen reader reads. */
  plain: string;
  /** The themed name of the term, shown beside it where there is room. */
  themed?: string;
  /** The value, already formatted. "Not recorded" rather than an empty cell. */
  value: string;
  /** A sentence under the value: a caveat, a unit note, a source. */
  note?: string;
}
