# The accessibility audit — the design system

`npm run a11y` is the earlier exit criterion: The definition of done says the UI meets WCAG AA, and this
is what checks it. It drives Chromium over **every route the app has**, in both
themes, at 375×812 and 1024×768, with `prefers-reduced-motion` both ways on
Morning Rounds, and runs [axe-core](https://github.com/dequelabs/axe-core) on
each page. A `serious` or `critical` violation of a WCAG rule fails the run.
Everything else it finds — `moderate` and `minor`, and the best-practice rules —
is printed per route and per theme with the rule id and the first offending
selector, so the owner of that route can go straight to it.

## Running it

Two things have to exist first. From the repository root:

```sh
# 1. The API, in mock mode. It serves fixtures and contacts nothing.
PYTHONPATH=api:. MOH_MOCK_MODE=true .venv/bin/uvicorn app.main:app --port 8000

# 2. A production build of the web app.
cd web && npm run build
```

Then, still in `web/`:

```sh
npm run a11y
```

The audit starts `build/index.js` itself and puts a small proxy in front of it
that sends `/api/` to the API and everything else to the app — the same split
the deployment's Nginx makes — so server-side `load` functions reach the API
exactly as they do in production. Nothing is left running afterwards.

| Variable            | Default                 | What it does                                                                                       |
| ------------------- | ----------------------- | -------------------------------------------------------------------------------------------------- |
| `MOH_API_URL`       | `http://127.0.0.1:8000` | Where the API is.                                                                                  |
| `MOH_A11Y_URL`      | —                       | Audit an app that is already running (a `vite dev` server, a deployment) instead of starting one.  |
| `MOH_A11Y_CHROMIUM` | Playwright's own        | The Chromium executable. On this project's CI image it is `/opt/pw-browsers/chromium`.             |
| `MOH_A11Y_ONLY`     | —                       | Audit only the routes whose path contains this text, e.g. `MOH_A11Y_ONLY=/journal`. For iterating. |
| `MOH_A11Y_REPORT`   | —                       | Also write the tables to this file as Markdown, for a pull request body or a releases note.        |
| `MOH_SPECIMEN_ID`   | the first fixture plant | The specimen every per-specimen route is audited with.                                             |

Never run `playwright install` here: the browsers are preinstalled, and the
install step is what the CI image exists to avoid.

## The route list

`AUDIT_ROUTES` in `audit.ts` is the one list, exported so the test suite's
end-to-end suite can walk the same routes. Importing the module runs
nothing; the audit starts only when `audit.ts` is the script Node was given.
A route that is not in the list is not audited — add the route the day it is
built, not the day someone notices.

`/register` and `/office` are in the plan and in the navigation bar but have no
page yet, so what is audited at those paths today is the error page. They stay
in the list so that when they land they are audited without anybody remembering.

## Reading the tables

The first table is one row per page load: route, owner, theme, viewport, HTTP status, and how many findings of each impact.
`incomplete` is what axe could not decide — usually a colour it could not
measure because something is painted over something else — and is worth a look
by hand rather than a fix.

The second table is one row per distinct finding. `FAIL` in the first column is
what fails the run; `wcag` is a WCAG rule below the failing threshold; and
`best-practice` is an axe rule that is not a WCAG criterion, reported because it
is usually right but never counted.

Findings in another parts of the project's directory are **listed, not fixed** here (rule
2): the pull request that runs the audit carries them with the route, the rule,
the selector and the fix that would be made, and A routes them.
