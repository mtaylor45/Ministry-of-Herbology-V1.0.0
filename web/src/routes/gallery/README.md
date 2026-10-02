# Component gallery — the design system

Owned by the design system, not the app's screens, even though it sits under `routes/`. It renders every
design-system component in both themes on one page, with no API, no fixtures
and no store behind it, so a component can be looked at without running the
rest of the app.

The gallery itself lives in `web/src/lib/ui/gallery/`; the route here is the
handful of lines that mount it. See the design.
