/** Theme switching: both themes are first-class, and the choice survives. */

import { describe, expect, it } from 'vitest';
import ThemeSwitcher from './ThemeSwitcher.svelte';
import {
  DEFAULT_THEME_CHOICE,
  THEMES,
  THEME_OPTIONS,
  THEME_STORAGE_KEY,
  applyTheme,
  isThemeChoice,
  readThemeChoice,
  resolveTheme,
  type ThemeTarget,
} from './theme';
import { count, html, text } from './render';

function target(prefersDark = false) {
  const store = new Map<string, string>();
  const root = { dataset: {} as Record<string, string>, style: { colorScheme: '' } };
  const meta = {
    content: '',
    setAttribute: (_: string, value: string) => void (meta.content = value),
  };
  const storage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
  };
  return { root, meta, storage, prefersDark, store } satisfies ThemeTarget & {
    store: Map<string, string>;
  };
}

describe('resolveTheme', () => {
  it('follows the device only when asked to', () => {
    expect(resolveTheme('system', true)).toBe('greenhouse');
    expect(resolveTheme('system', false)).toBe('parchment');
    expect(resolveTheme('parchment', true)).toBe('parchment');
    expect(resolveTheme('greenhouse', false)).toBe('greenhouse');
  });
});

describe('applyTheme', () => {
  it('writes data-theme, the colour scheme and the browser chrome colour', () => {
    const env = target();
    expect(applyTheme('greenhouse', env)).toBe('greenhouse');
    expect(env.root.dataset.theme).toBe('greenhouse');
    expect(env.root.style.colorScheme).toBe('dark');
    expect(env.meta.content).toBe('#111722');
  });

  it('remembers the choice, not the theme it resolved to', () => {
    // Otherwise "match my device" quietly freezes into whatever it was at the time.
    const env = target(true);
    applyTheme('system', env);
    expect(env.store.get(THEME_STORAGE_KEY)).toBe('system');
    expect(env.root.dataset.theme).toBe('greenhouse');
  });

  it('applies the theme even when storage refuses to take it', () => {
    const env = target();
    const blocked = {
      ...env,
      storage: {
        getItem: () => null,
        setItem: () => {
          throw new Error('storage is blocked in private mode');
        },
      },
    };
    expect(() => applyTheme('parchment', blocked)).not.toThrow();
    expect(blocked.root.dataset.theme).toBe('parchment');
  });
});

describe('readThemeChoice', () => {
  it('falls back to the light default for anything it does not recognise', () => {
    // the design, question 3: someone who has never opened the switcher gets
    // parchment, whatever their device prefers. Following the device is a
    // choice they make and we store, not the state they start in.
    expect(DEFAULT_THEME_CHOICE).toBe('parchment');
    expect(readThemeChoice({ getItem: () => 'greenhouse' })).toBe('greenhouse');
    expect(readThemeChoice({ getItem: () => 'system' })).toBe('system');
    expect(readThemeChoice({ getItem: () => 'mauve' })).toBe('parchment');
    expect(readThemeChoice({ getItem: () => null })).toBe('parchment');
    expect(
      readThemeChoice({
        getItem: () => {
          throw new Error('blocked');
        },
      }),
    ).toBe('parchment');
  });

  it('still gives a dark-mode phone parchment when nothing is stored', () => {
    // The regression this guards: the old default was `system`, so a dark-mode
    // phone silently got the greenhouse. It is one tap away, not the start.
    const env = target(true);
    expect(applyTheme(readThemeChoice(env.storage), env)).toBe('parchment');
  });

  it('knows a valid choice from a stray string', () => {
    expect(isThemeChoice('system')).toBe(true);
    expect(isThemeChoice('parchment')).toBe(true);
    expect(isThemeChoice('sepia')).toBe(false);
  });
});

describe('ThemeSwitcher', () => {
  it('offers both themes and the device setting, each with a plain label', () => {
    const markup = html(ThemeSwitcher, {});
    expect(count(markup, 'input')).toBe(THEME_OPTIONS.length);
    for (const option of THEME_OPTIONS) {
      expect(text(markup)).toContain(option.plain);
      if (option.themed) expect(text(markup)).toContain(option.themed);
    }
  });

  it('treats both themes as first-class, not one as an afterthought', () => {
    const choices = THEME_OPTIONS.map((option) => option.choice);
    for (const theme of THEMES) expect(choices).toContain(theme);
  });

  it('is a radio group, so a keyboard moves through it the expected way', () => {
    expect(html(ThemeSwitcher, {})).toContain('type="radio"');
  });
});
