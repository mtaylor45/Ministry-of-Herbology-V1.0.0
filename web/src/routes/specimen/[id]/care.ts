/** Care values: what each one is called, how it reads, and how it is corrected.
 *
 * the design is the whole of this module's reason to exist. Every care value
 * shows its source and its confidence, every one is editable, and a value with
 * no citation reads as unknown rather than being hidden or quietly filled in.
 * the design made that load-bearing rather than tidy: with no soil probe in the
 * house, the water balance is the only thing deciding whether an outdoor plant
 * gets watered, and several `water_k_c` values are uncited. The person holding
 * the watering can is the one who has to know that.
 */

import type { Status } from '$ui';
import type { CareValue, Confidence } from './api';

export interface CareField {
  /** Plain-language name. Always shown. */
  plain: string;
  /** Themed name, shown beside the plain one where there is room. */
  themed?: string;
  /** A sentence saying what the number is for, in the editor. */
  hint?: string;
  unit?: string;
  /** The name as it reads mid-sentence, where lowercasing the plain name would
   *  mangle it — "lowest soil pH", not "lowest soil ph". */
  lower?: string;
  kind: 'number' | 'text' | 'boolean';
  /** Bounds for the editor, where the field has natural ones. */
  min?: number;
  max?: number;
  step?: number;
  /** The `SpecimenUpdate` field that corrects this value for this plant only. */
  overrideField?: string;
}

/** The fields the contract names, in the order a keeper reads them. */
export const CARE_FIELDS: Record<string, CareField> = {
  water_k_c: {
    plain: 'Water need',
    themed: 'Thirst',
    hint: 'How thirsty this plant is next to open water. The water balance multiplies the day’s evaporation by it.',
    kind: 'number',
    min: 0,
    max: 2,
    step: 0.05,
    overrideField: 'water_k_c_override',
  },
  water_interval_days: {
    plain: 'Days between waterings',
    themed: 'Interval',
    hint: 'Used indoors, where there is no rain and no evaporation figure to work from.',
    unit: 'days',
    kind: 'number',
    min: 1,
    max: 120,
    step: 1,
    overrideField: 'water_interval_days_override',
  },
  min_temp_c: {
    plain: 'Lowest safe temperature',
    themed: 'Cold it will bear',
    hint: 'The frost guard warns when the forecast low comes within 1.7 °C of this.',
    unit: '°C',
    kind: 'number',
    min: -40,
    max: 30,
    step: 0.5,
    overrideField: 'min_temp_c_override',
  },
  max_temp_c: {
    plain: 'Highest safe temperature',
    unit: '°C',
    kind: 'number',
    min: 0,
    max: 60,
    step: 0.5,
  },
  light_label: { plain: 'Light', themed: 'Appetite for sun', kind: 'text' },
  soil_ph_min: {
    plain: 'Lowest soil pH',
    lower: 'lowest soil pH',
    kind: 'number',
    min: 3,
    max: 10,
    step: 0.1,
  },
  soil_ph_max: {
    plain: 'Highest soil pH',
    lower: 'highest soil pH',
    kind: 'number',
    min: 3,
    max: 10,
    step: 0.1,
  },
  soil_type: { plain: 'Soil', kind: 'text' },
  humidity_min_pct: {
    plain: 'Lowest comfortable humidity',
    unit: '%',
    kind: 'number',
    min: 0,
    max: 100,
    step: 1,
  },
  fertilizer_note: { plain: 'Feeding', themed: 'Sustenance', kind: 'text' },
  toxic_to_pets: { plain: 'Toxic to pets', kind: 'boolean' },
  toxic_to_children: { plain: 'Toxic to children', kind: 'boolean' },
  usda_zone_min: { plain: 'Coldest hardiness zone', kind: 'text' },
  usda_zone_max: { plain: 'Warmest hardiness zone', kind: 'text' },
};

/** Turn `water_k_c` into "Water k c" — a last resort, not a design. A field the
 *  contract grows and this table has not caught up with still gets a readable
 *  label rather than a column name. */
export function humanise(field: string): string {
  const words = field.replace(/_/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function careField(field: string): CareField {
  return CARE_FIELDS[field] ?? { plain: humanise(field), kind: 'text' };
}

/** The field's name as it reads inside a sentence, such as a button's label. */
export function sentenceName(field: string): string {
  const spec = careField(field);
  return spec.lower ?? spec.plain.toLowerCase();
}

/** Units are stored SI and terse; a reader wants the symbol.
 *
 *  The contract leaves `CareValue.unit` a free string, and the fixtures write
 *  temperatures as `C`. Showing "10 C" where the rest of the app says "10 °C"
 *  is the kind of small inconsistency that makes a number look untrustworthy,
 *  so the symbols are normalised on the way out. */
const UNIT_SYMBOLS: Record<string, string> = {
  c: '°C',
  celsius: '°C',
  degc: '°C',
  f: '°F',
  pct: '%',
  percent: '%',
  l: 'litres',
  litre: 'litres',
};

export function displayUnit(unit: string | null | undefined): string | undefined {
  if (!unit) return undefined;
  const trimmed = unit.trim();
  if (!trimmed) return undefined;
  return UNIT_SYMBOLS[trimmed.toLowerCase()] ?? trimmed;
}

/** The order care values are read in: what waters it, what kills it, then the rest. */
const FIELD_ORDER = [
  'water_k_c',
  'water_interval_days',
  'min_temp_c',
  'max_temp_c',
  'light_label',
  'humidity_min_pct',
  'soil_ph_min',
  'soil_ph_max',
  'soil_type',
  'fertilizer_note',
  'usda_zone_min',
  'usda_zone_max',
  'toxic_to_pets',
  'toxic_to_children',
];

export function sortCareValues(values: readonly CareValue[]): CareValue[] {
  const rank = (field: string) => {
    const index = FIELD_ORDER.indexOf(field);
    return index === -1 ? FIELD_ORDER.length : index;
  };
  return [...values].sort(
    (a, b) => rank(a.field) - rank(b.field) || a.field.localeCompare(b.field),
  );
}

export const LIGHT_LABELS: Record<string, string> = {
  full_sun: 'Full sun',
  part_sun: 'Part sun',
  part_shade: 'Part shade',
  full_shade: 'Full shade',
  bright_indirect: 'Bright, indirect light',
  low_light: 'Low light',
  unknown: 'Not known',
};

/** A care value as a reader sees it, unit included. Never "null", never "[object Object]". */
export function formatValue(value: unknown, field: string, unit?: string | null): string {
  const spec = careField(field);
  if (value === null || value === undefined || value === '') return 'Not recorded';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (field === 'light_label' && typeof value === 'string') {
    return LIGHT_LABELS[value] ?? humanise(value);
  }
  const suffix = displayUnit(unit) ?? spec.unit;
  if (typeof value === 'number') {
    const shown = Number.isInteger(value) ? String(value) : String(Number(value.toFixed(2)));
    return suffix ? `${shown} ${suffix}` : shown;
  }
  if (Array.isArray(value)) return value.join(', ');
  const text = String(value);
  return suffix ? `${text} ${suffix}` : text;
}

/** How much to trust a value, as a pill — themed word, plain meaning, tone.
 *
 *  `unknown` is the state the whole exists for, so it reads as a
 *  warning rather than as a blank: nothing about it is quiet. */
export function confidenceStatus(confidence: Confidence, isUserOverride = false): Status {
  if (isUserOverride) {
    return {
      themed: 'By your own hand',
      plain: 'Your correction — overrides every source',
      tone: 'thriving',
    };
  }
  switch (confidence) {
    case 'high':
      return { themed: 'Well attested', plain: 'High confidence', tone: 'thriving' };
    case 'medium':
      return { themed: 'Attested', plain: 'Medium confidence', tone: 'sated' };
    case 'low':
      return { themed: 'Thinly attested', plain: 'Low confidence — check it', tone: 'parched' };
    case 'unknown':
    default:
      return { themed: 'Unattested', plain: 'Unknown — no source for this', tone: 'ailing' };
  }
}

/** True when the value is a guess the reader must not mistake for a fact. */
export function isUncited(value: CareValue): boolean {
  return !value.is_user_override && (value.confidence === 'unknown' || value.source === null);
}

/** Where an edit to this field goes, given the contract's two override routes.
 *
 *  A specimen override corrects this plant; a care-value override corrects the
 *  species for every plant of it. The first is what a keeper almost always
 *  means, so it wins wherever the contract offers it.
 */
export function editTarget(
  field: string,
  specimenId: string,
  speciesId: string | null,
):
  | { route: 'specimen'; id: string; overrideField: string; scope: string }
  | { route: 'species'; id: string; field: string; scope: string }
  | null {
  const spec = careField(field);
  if (spec.overrideField) {
    return {
      route: 'specimen',
      id: specimenId,
      overrideField: spec.overrideField,
      scope: 'This plant only. Other plants of the same species keep the sourced value.',
    };
  }
  if (!speciesId) return null;
  return {
    route: 'species',
    id: speciesId,
    field,
    scope: 'Every plant of this species, because the contract records this value on the species.',
  };
}

export const SOURCE_KINDS: Record<string, string> = {
  powo: 'Plants of the World Online',
  gbif: 'GBIF backbone taxonomy',
  wikipedia: 'Wikipedia',
  wikidata: 'Wikidata',
  usda: 'USDA PLANTS',
  perenual: 'Perenual',
  user: 'Your own correction',
};

export function sourceKind(kind: string): string {
  return SOURCE_KINDS[kind] ?? humanise(kind);
}
