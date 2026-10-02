/** Test helper: render a component to HTML without a browser.
 *
 * The suite runs in Node, so components are checked through their server
 * render. That covers what matters most in this library — the pairing rule,
 * labelling, ARIA state and disabled handling — and it keeps the design system
 * testable without adding a DOM emulator to the project's dependencies.
 */

import { render as ssr } from 'svelte/server';
import type { Component } from 'svelte';

export function html(component: Component<any>, props: Record<string, unknown> = {}): string {
  return ssr(component as never, { props } as never).body;
}

/** Strip Svelte's SSR comments and scoped-class noise for readable assertions. */
export function text(markup: string): string {
  return markup
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/** The attributes of the first element matching a tag name. */
export function attrs(markup: string, tag: string): Record<string, string> {
  const match = new RegExp(`<${tag}\\b([^>]*)>`).exec(markup);
  if (!match) throw new Error(`no <${tag}> in markup`);
  const found: Record<string, string> = {};
  for (const attr of match[1].matchAll(/([a-zA-Z-]+)(?:="([^"]*)")?/g)) {
    found[attr[1]] = attr[2] ?? '';
  }
  return found;
}

/** How many times a tag appears. */
export function count(markup: string, tag: string): number {
  return markup.match(new RegExp(`<${tag}\\b`, 'g'))?.length ?? 0;
}
