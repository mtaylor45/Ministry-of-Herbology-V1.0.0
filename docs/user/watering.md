# Watering, and the mornings the sky does it for you

that decides an outdoor watering.*

Morning Rounds has two lists of waterings, and the difference between them is
the point of this page.

| On the round | Themed | Plain |
| --- | --- | --- |
| **Due** | *Parched — attend to it today* | This plant needs water |
| **Settled without you** | *Sated by the heavens* | Rain covered it; nothing to do |

A watering that the rain covered does **not** disappear. It moves into the
second list and stays there for the day, marked with what settled it. That is
deliberate: a task that vanishes because it rained looks exactly like a task
that was never scheduled, and you would have no way to tell whether the app had
thought about the plant at all.

## Where the decision comes from

For an outdoor plant, the Ministry keeps a running figure for how much water the
soil has lost and not got back — the *deficit*. Each day it grows by how much
the plant and the weather between them took out, and it shrinks by the rain that
landed on it. When it crosses the plant's threshold, a watering falls due.

You can see the whole calculation on the plant's **Tending** facet: the last two
weeks of the balance, day by day, with the rainfall and the evaporation figure
each day contributed.

Three things decide how fast a deficit grows:

- **The plant.** A thirsty species loses water faster than a drought-adapted
  one. The coefficient comes from a cited source, and the citation is on the
  care profile.
- **The pot.** A small container holds very little spare water and reaches its
  threshold in days. Open ground draws on a much deeper reserve and takes weeks.
- **The sky.** Hot, bright, windy days take more out than cool, dull ones.

## Why a plant under a roof is still thirsty after a storm

Rain only counts where rain lands. A plant on a covered porch, under an eave or
in a greenhouse is marked **covered** on its location, and rainfall is not
applied to it at all — so it can go on getting drier through a downpour, and the
app will go on asking you to water it. That is correct, and it is the most
common surprise in the whole feature.

If a plant is in the wrong place, change its location in **The Register** and the
next round will use the new one.

## Nothing here measures your soil

The Ministry has no moisture probe, and v1.0 does not expect one. **Every
watering this app asks for is a calculation, not a measurement.** It is a good
calculation — it uses the real weather at your site — but it has never touched
the ground, and it does not know that you emptied a watering can over the
rosemary on Sunday unless you told it.

So the app says how sure it is, on every watering, and it is never completely
sure:

| It says | It means |
| --- | --- |
| **Medium** | Modelled from real weather and a cited care value. This is the best a watering gets. |
| **Low** | Something is degraded — most often the weather the balance was built from has stopped arriving, so the deficit has stopped growing while the plant has not stopped drying. |
| **Unknown** | Nobody has cited a watering interval for this species. The schedule is a guess with arithmetic done to it. |

Where a watering is worth less than it looks, the reason is written out in plain
words on the task itself — in the app, and in the calendar event's description.
You are not expected to go looking for it.

You can always overrule the model. Edit the care value on the **Tending** facet,
or write your own care rule, and yours wins.

## Plants the round could not speak for

Below the two lists there is a third, shorter one: plants the round has nothing
to say about, each with the reason. A dormant plant is there because its care
rule suspends watering rather than stretching it — it is off the schedule until
it wakes, not on a longer one. A plant with no cited watering interval and no
rule of your own is there too.

This list exists so that silence has only one meaning. A plant that is not on
the round is a plant that needs nothing; a plant the app could not judge is
named.

## In your calendar

If you subscribe to a feed (**Ministry Office → Calendar feeds**), a watering
appears as an all-day event. When rain settles it, the event is **cancelled** —
the same event, withdrawn — rather than quietly deleted, because a subscribed
calendar has no other way to tell your phone that it is gone. You may see it
struck through, or disappear, depending on your calendar app.

Subscribed feeds refresh slowly. Google in particular can take twelve hours or
more. If you need a watering to reach your phone sooner, the Ministry Office
offers direct push instead.

## Seeing it happen before you trust it

You do not have to wait for weather to find out whether any of this works. The
Ministry ships three recorded weeks — a storm, a drought and a frost — and you
can stand the whole app inside one of them:

```
MOH_SCENARIO=storm
MOH_SCENARIO_DAY=2026-07-07
```

That is the morning after 38 mm of rain. Open Morning Rounds and the terrace
lemon is in **settled without you**, marked as covered by the rain, while the
two plants on the covered porch are still asking to be watered. Set
`MOH_SCENARIO=drought` instead and nothing is ever settled: the
deficits climb for three weeks and the waterings stay due.

Leave both unset — which is how the Ministry ships — and you get your own
weather.

---

*See also: [Reading care values, sources and confidence](README.md) · the
water-balance equation and the fixtures that test it are described in
the project notes and `fixtures/README.md`.*
