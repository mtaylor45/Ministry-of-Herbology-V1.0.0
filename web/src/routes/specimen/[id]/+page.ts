/** `/specimen/:id` is not a page of its own — it is whichever facet you were
 *  last on, and by default the Register entry. */

import { redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';
import { facetPath } from './facets';

export const load: PageLoad = ({ params }) => {
  redirect(307, facetPath(params.id, 'register'));
};
