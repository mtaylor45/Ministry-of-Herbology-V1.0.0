/** Themed status strings, each paired with a plain one.
 *  Nothing in the UI may show the themed half alone. */

export interface Status {
  themed: string;
  plain: string;
  tone: 'parched' | 'sated' | 'frost' | 'thriving' | 'ailing';
}

export const STATUS = {
  parched: { themed: 'Parched', plain: 'Water today', tone: 'parched' },
  satedByRain: { themed: 'Sated by the heavens', plain: 'Rain covered it', tone: 'sated' },
  satedBySensor: { themed: 'Soil still damp', plain: 'Sensor says no water needed', tone: 'sated' },
  frostComing: {
    themed: 'A killing frost approaches',
    plain: 'Bring indoors before tonight',
    tone: 'frost',
  },
  thriving: { themed: 'In fine fettle', plain: 'Healthy', tone: 'thriving' },
  struggling: { themed: 'Out of sorts', plain: 'Struggling', tone: 'ailing' },
  dormant: { themed: 'Slumbering', plain: 'Dormant for the season', tone: 'sated' },
} as const satisfies Record<string, Status>;

export type StatusKey = keyof typeof STATUS;
