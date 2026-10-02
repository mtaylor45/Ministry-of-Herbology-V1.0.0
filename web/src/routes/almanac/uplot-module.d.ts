/** `uplot` ships its declarations at `dist/uPlot.d.ts` but its `package.json`
 *  names no `types` entry, so the bare specifier resolves to a value with no
 *  type at all. Pointing one at the other here keeps uPlot's own types — the
 *  alternative is `any` on every chart option in the app, which is how a typo
 *  in an axis spec becomes a blank chart nobody notices. */
declare module 'uplot' {
  import uPlot from 'uplot/dist/uPlot';
  export = uPlot;
}
