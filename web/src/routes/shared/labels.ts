/** Words more than one screen needs, kept in one place.
 *
 * The Specimen facets named the task types first; Morning Rounds reads the same
 * `task_type` values off the same endpoint and must call them the same thing. A
 * second table would be a second vocabulary, and the day they disagree is the
 * day "Fertilize" and "Feed" both mean one job.
 */

/** `TaskType` from the frozen contract, in the words a person uses. */
export const TASK_TYPES: Record<string, string> = {
  water: 'Water',
  fertilize: 'Fertilize',
  mist: 'Mist',
  prune: 'Prune',
  repot: 'Repot',
  inspect: 'Inspect for pests',
  bring_indoors: 'Bring indoors',
  return_outdoors: 'Put back outside',
  cover: 'Cover against frost',
  rotate: 'Rotate',
};

/** The plain name of a task type, or the raw value when it is one this build
 *  has never heard of. A job nobody can name still has to be doable. */
export function taskTypeLabel(taskType: string): string {
  return TASK_TYPES[taskType] ?? taskType;
}

/** A date as a person writes it, or a plain phrase when there is no date. */
export function formatDate(value: string | null | undefined, fallback = 'Not recorded'): string {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
}
