/** Sample content for the gallery.
 *
 * Invented plants and places, not fixture data: the gallery must render with
 * no API, no database and no `fixtures/` import. Nothing here is a plant fact
 * — the numbers are shapes for a layout, not care advice.
 */

import type { IconName } from '../icons';
import type { Member } from '../member';
import type { SelectOption } from '../types';

export interface SampleTask {
  id: string;
  themed: string;
  plain: string;
  meta: string;
}

export const SAMPLE_TASKS: SampleTask[] = [
  {
    id: 'task-1',
    themed: 'The basil thirsts',
    plain: 'Water the basil',
    meta: 'Kitchen sill — due today',
  },
  {
    id: 'task-2',
    themed: 'Turn the fern about',
    plain: 'Rotate the fern',
    meta: 'Hallway — due today',
  },
  {
    id: 'task-3',
    themed: 'Feed the tomatoes',
    plain: 'Fertilise the tomatoes',
    meta: 'South bed — due tomorrow',
  },
];

export interface SampleSpecimen {
  id: string;
  themed: string;
  plain: string;
  meta: string;
  icon: IconName;
}

export const SAMPLE_SPECIMENS: SampleSpecimen[] = [
  {
    id: 'spec-1',
    themed: 'Sweet basil',
    plain: 'Ocimum basilicum',
    meta: 'Kitchen sill · indoors',
    icon: 'leaf',
  },
  {
    id: 'spec-2',
    themed: 'Lady fern',
    plain: 'Athyrium filix-femina',
    meta: 'Hallway · indoors',
    icon: 'seedling',
  },
  {
    id: 'spec-3',
    themed: 'Garden tomato',
    plain: 'Solanum lycopersicum',
    meta: 'South bed · outdoors',
    icon: 'pin',
  },
];

/** An invented household. The fixture one has the same three roles. */
export const SAMPLE_MEMBERS: Member[] = [
  { id: 'member-1', name: 'Wren', role: 'keeper' },
  { id: 'member-2', name: 'Alder', role: 'tender' },
  { id: 'member-3', name: 'Moss', role: 'observer' },
];

export const SAMPLE_LOCATIONS: SelectOption[] = [
  { value: 'kitchen-sill', themed: 'The kitchen sill', plain: 'Kitchen sill' },
  { value: 'greenhouse-bench', themed: 'The greenhouse bench', plain: 'Greenhouse bench' },
  { value: 'south-bed', themed: 'The south bed', plain: 'South bed' },
  { value: 'cold-frame', plain: 'Cold frame', disabled: true },
];
