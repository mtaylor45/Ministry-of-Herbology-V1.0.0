# Vendored fonts

Served from this app's own origin. Nothing here is fetched from a third party at
runtime: the design says nothing may depend on a service the operator did not
choose, and a font CDN is both a request to someone else's server on every load
and an offline failure in a garden with no signal.

| File                             | Face                                                      | Licence                               |
| -------------------------------- | --------------------------------------------------------- | ------------------------------------- |
| `cormorant-garamond-latin.woff2` | Cormorant Garamond, variable `wght` 300–700, Latin subset | SIL Open Font Licence 1.1 — `OFL.txt` |

`OFL.txt` is the licence text as published beside the font in the release the
file was built from, committed unmodified. Copyright 2015 the Cormorant Project
Authors (github.com/CatharsisFonts/Cormorant), designed by Christian Thalmann.
the design requires the licence to be confirmed against the release actually
downloaded rather than assumed; it was, and this is the text.

## How the file was built

Source: the upstream release of the variable font, `CormorantGaramond[wght].ttf`
(1.14 MB). Subset with `fonttools` to the characters the app sets — Basic Latin,
Latin-1 Supplement, Latin Extended-A for botanical names, and the punctuation
the copy uses — keeping the weight axis so headings at 600 and themed labels at
400 come from one file:

```
python -m fontTools.subset CormorantGaramond[wght].ttf \
  --unicodes="U+0000-00FF,U+0100-017F,U+2013-2014,U+2018-201A,U+201C-201E,\
U+2020-2022,U+2026,U+2039-203A,U+2044,U+2212" \
  --layout-features="kern,liga,clig,calt,onum,locl,mark,mkmk,ccmp" \
  --flavor=woff2 --with-zopfli \
  --name-IDs="*" --name-legacy --name-languages="*" \
  --output-file=cormorant-garamond-latin.woff2
```

`--name-IDs="*"` keeps the upstream name and copyright records in the subset,
which the OFL's attribution requirement wants. 35 KB out.

The `@font-face` rule and its `unicode-range` are in
`web/src/lib/ui/fonts.css`: a character outside the subset falls back through
the system serif stack rather than rendering as a box.
