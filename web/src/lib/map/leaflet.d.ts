/** Leaflet ships no types and this project does not install `@types/leaflet`.
 *
 * `web/package.json` is not the maps module's to change, and a
 * dependency is not a thing to add through a map component's pull request
 * anyway. The surface actually used is small and lives in one place —
 * `GroundsMap.svelte` — where each call is named in a comment.
 *
 * Declaring the module `any` here rather than sprinkling `@ts-expect-error`
 * keeps the untyped edge at the boundary, where it can be seen, instead of
 * scattered through the component. If `@types/leaflet` is added later this
 * file is the only thing to delete.
 */
declare module 'leaflet';
declare module 'leaflet/dist/leaflet.css';
