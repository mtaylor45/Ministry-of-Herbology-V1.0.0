/** The icon set: original line drawings on a 24×24 grid.
 *
 * Drawn here rather than pulled from a library because the design rules out
 * franchise assets and because an icon is never the only carrier of meaning in
 * this app — every one of them sits beside a plain-language string. Paths are
 * stroked with `currentColor`, so an icon takes the colour of the text it
 * accompanies and inherits its contrast.
 */

export interface IconSpec {
  /** Path `d` strings, stroked in order. */
  paths: string[];
  /** A default plain-language name, for the rare icon-only control. */
  plain: string;
}

export const ICONS = {
  leaf: {
    plain: 'Plant',
    paths: ['M4 20C4 12 10 6 20 4c1 10-5 17-13 17H4z', 'M5 19c4-3 7-6.5 9-10.5'],
  },
  water: {
    plain: 'Water',
    paths: ['M12 3s6 6.5 6 10.5a6 6 0 0 1-12 0C6 9.5 12 3 12 3z'],
  },
  rain: {
    plain: 'Rain',
    paths: [
      'M7 15a4 4 0 0 1 .6-8 5 5 0 0 1 9.5 1.4A3.5 3.5 0 0 1 17 15H7z',
      'M8 18l-1 3M12 18l-1 3M16 18l-1 3',
    ],
  },
  sun: {
    plain: 'Sun',
    paths: [
      'M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0z',
      'M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4',
    ],
  },
  moon: {
    plain: 'Night',
    paths: ['M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z'],
  },
  frost: {
    plain: 'Frost',
    paths: ['M12 2v20M3.5 7l17 10M20.5 7l-17 10', 'M9 4.5L12 7l3-2.5M9 19.5L12 17l3 2.5'],
  },
  thermometer: {
    plain: 'Temperature',
    paths: ['M14 14.8V5a2 2 0 1 0-4 0v9.8a4 4 0 1 0 4 0z'],
  },
  seedling: {
    plain: 'New plant',
    paths: [
      'M12 21v-8',
      'M12 13C12 8.5 8.5 6 4 6c0 4.5 3.5 7 8 7z',
      'M12 13c0-4.5 3.5-7 8-7 0 4.5-3.5 7-8 7z',
    ],
  },
  quill: {
    plain: 'Log',
    paths: ['M4 20c6.5 0 16-4.5 16-16-6.5 0-14.5 4.5-14.5 12.5', 'M4 20l6-6'],
  },
  book: {
    plain: 'Journal',
    paths: [
      'M4 4h6a3 3 0 0 1 3 3v13a3 3 0 0 0-3-3H4z',
      'M20 4h-6a3 3 0 0 0-3 3v13a3 3 0 0 1 3-3h6z',
    ],
  },
  pin: {
    plain: 'Location',
    paths: [
      'M12 22s7-7.5 7-12a7 7 0 1 0-14 0c0 4.5 7 12 7 12z',
      'M14.5 10a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z',
    ],
  },
  search: {
    plain: 'Search',
    paths: ['M17 10.5a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0z', 'M20 20l-4.6-4.6'],
  },
  check: {
    plain: 'Done',
    paths: ['M4 13l5 5L20 6'],
  },
  close: {
    plain: 'Close',
    paths: ['M6 6l12 12M18 6L6 18'],
  },
  chevronRight: {
    plain: 'More',
    paths: ['M9 5l7 7-7 7'],
  },
  chevronDown: {
    plain: 'Expand',
    paths: ['M5 9l7 7 7-7'],
  },
  plus: {
    plain: 'Add',
    paths: ['M12 5v14M5 12h14'],
  },
  warning: {
    plain: 'Warning',
    paths: ['M12 3l9.5 17H2.5L12 3z', 'M12 9.5v4.5M12 17.3h.01'],
  },
  stale: {
    plain: 'Out of date',
    paths: ['M20.5 12a8.5 8.5 0 1 1-2.6-6.1', 'M18.5 3v3h-3', 'M12 7.5V12l3 2'],
  },
  bell: {
    plain: 'Reminder',
    paths: ['M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6z', 'M10 19a2.2 2.2 0 0 0 4 0'],
  },
  camera: {
    plain: 'Photo',
    paths: ['M3 8h3.5L8.5 5h7l2 3H21v12H3z', 'M15.5 13.5a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0z'],
  },
  trash: {
    plain: 'Delete',
    paths: ['M4 7h16M10 7V4.5h4V7', 'M6 7l1 13h10l1-13'],
  },
  gear: {
    plain: 'Settings',
    paths: [
      'M12 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7z',
      'M12 2.5l1.7 2.6 3-.6.6 3 2.6 1.7-1.4 2.7 1.4 2.7-2.6 1.7-.6 3-3-.6L12 21.5l-1.7-2.6-3 .6-.6-3L4.1 14.8l1.4-2.7-1.4-2.7 2.6-1.7.6-3 3 .6L12 2.5z',
    ],
  },
} as const satisfies Record<string, IconSpec>;

export type IconName = keyof typeof ICONS;

export const ICON_NAMES = Object.keys(ICONS) as IconName[];
