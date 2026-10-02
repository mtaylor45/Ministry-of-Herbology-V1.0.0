<script lang="ts">
  import Button from '../Button.svelte';
  import Card from '../Card.svelte';
  import Dialog from '../Dialog.svelte';
  import EmptyState from '../EmptyState.svelte';
  import Icon from '../Icon.svelte';
  import ListRow from '../ListRow.svelte';
  import MemberPicker from '../MemberPicker.svelte';
  import NumberField from '../NumberField.svelte';
  import SearchInput from '../SearchInput.svelte';
  import SelectField from '../SelectField.svelte';
  import Skeleton from '../Skeleton.svelte';
  import StaleNotice from '../StaleNotice.svelte';
  import StatusPill from '../StatusPill.svelte';
  import TaskCheckbox from '../TaskCheckbox.svelte';
  import TextField from '../TextField.svelte';
  import ThemeSwitcher from '../ThemeSwitcher.svelte';
  import Toggle from '../Toggle.svelte';
  import { ICON_NAMES, ICONS } from '../icons';
  import { selectionState, selectionSummary, toggleAll, toggleOne } from '../selection';
  import { STATUS } from '../status';
  import { SAMPLE_TASKS, SAMPLE_SPECIMENS, SAMPLE_LOCATIONS, SAMPLE_MEMBERS } from './samples';

  /** Every component in the library, once, with no API behind it. */
  let { theme }: { theme: string } = $props();

  let nickname = $state('Sunday');
  let potSize: number | null = $state(180);
  let location = $state('greenhouse-bench');
  let query = $state('');
  let notify = $state(true);
  let dialogOpen = $state(false);
  let actingAs = $state('member-2');
  let selected: Set<string> = $state(new Set([SAMPLE_TASKS[0].id]));

  const selectAll = $derived(selectionState(selected.size, SAMPLE_TASKS.length));
</script>

<h2 class="pane-title">{theme}</h2>

<section aria-labelledby="{theme}-buttons" class="group">
  <h3 id="{theme}-buttons">Buttons<span class="visually-hidden"> — {theme}</span></h3>
  <div class="row">
    <Button themed="Tend to it" plain="Water now" icon="water" />
    <Button variant="quiet" plain="Not today" />
    <Button variant="destructive" themed="Uproot" plain="Remove specimen" icon="trash" />
  </div>
  <div class="row">
    <Button plain="Saving" loading />
    <Button plain="Unavailable" disabled />
    <Button variant="quiet" plain="Disabled and quiet" disabled />
  </div>
  <Button plain="Add a specimen" icon="plus" full />
</section>

<section aria-labelledby="{theme}-status" class="group">
  <h3 id="{theme}-status">Status<span class="visually-hidden"> — {theme}</span></h3>
  <div class="row">
    <StatusPill status={STATUS.parched} />
    <StatusPill status={STATUS.satedByRain} />
    <StatusPill status={STATUS.frostComing} />
    <StatusPill status={STATUS.thriving} />
    <StatusPill status={STATUS.struggling} />
  </div>
</section>

<section aria-labelledby="{theme}-tasks" class="group">
  <h3 id="{theme}-tasks">
    Task completion — one tap and batch<span class="visually-hidden"> — {theme}</span>
  </h3>

  <!-- `meaning="selection"`: a tick gathers the row for the batch, the button
       at the foot does the completing. No strike-through, and the word is
       "Selected", because the plant has not been watered yet. -->
  <Card themed="Morning Rounds" plain="Due today — ticking selects" level={4}>
    <TaskCheckbox
      plain="Select all"
      themed="The whole round"
      meaning="selection"
      checkState={selectAll}
      meta={selectionSummary(selected.size, SAMPLE_TASKS.length)}
      onchange={() =>
        (selected = toggleAll(
          SAMPLE_TASKS.map((task) => task.id),
          selectAll,
        ))}
    />
    <hr />
    {#each SAMPLE_TASKS as task (task.id)}
      <TaskCheckbox
        themed={task.themed}
        plain={task.plain}
        meta={task.meta}
        meaning="selection"
        checked={selected.has(task.id)}
        onchange={() => (selected = toggleOne(selected, task.id))}
      />
    {/each}
    {#snippet footer()}
      <Button plain="Mark {selected.size} done" themed="Enter in the ledger" icon="check" />
    {/snippet}
  </Card>

  <!-- The default: the tick *is* the completion, so the row is struck through
       and says "Done". Both of these are in the app; the difference is the one
       thing J could not reach from a route. -->
  <Card themed="The ledger" plain="Already done — ticking completes" level={4}>
    <div class="stack">
      <TaskCheckbox
        themed="The basil is watered"
        plain="Water the basil"
        meta="Kitchen sill — done this morning"
        checked
      />
      <TaskCheckbox
        themed="The fern awaits"
        plain="Mist the fern"
        meta="Bathroom shelf — due today"
      />
    </div>
  </Card>
</section>

<section aria-labelledby="{theme}-brass" class="group">
  <h3 id="{theme}-brass">
    Antique gold, in three strengths<span class="visually-hidden"> — {theme}</span>
  </h3>
  <p class="note">
    Full-strength gold measures 1.74–2.30:1 on the light surfaces, so on parchment it may only
    decorate. Anything that carries meaning — a rule, a heading, a border you are meant to read
    something from — takes one of the two derived brasses. On the night greenhouse all three are the
    same colour, because there gold already passes.
  </p>
  <ul class="brass">
    <li>
      <span class="chip" style="background: var(--moh-gold-decor)" aria-hidden="true"></span>
      <span class="swatch-ink"
        ><code>--moh-gold-decor</code> decoration only — never text, never a meaningful border</span
      >
    </li>
    <li>
      <span class="chip" style="background: var(--moh-gold-line)" aria-hidden="true"></span>
      <span class="swatch-ink"><code>--moh-gold-line</code> borders, rules, hairlines (3:1)</span>
    </li>
    <li>
      <span class="chip" style="background: var(--moh-gold-ink)" aria-hidden="true"></span>
      <span class="swatch-ink" style="color: var(--moh-gold-ink)"
        ><code>--moh-gold-ink</code> gold set as text (4.5:1)</span
      >
    </li>
    <li>
      <span class="chip" style="background: var(--moh-sage)" aria-hidden="true"></span>
      <span class="swatch-ink" style="color: var(--moh-sage)"
        ><code>--moh-sage</code> botanical categories and diagrams</span
      >
    </li>
  </ul>
</section>

<section aria-labelledby="{theme}-seal" class="group">
  <h3 id="{theme}-seal">The Ministry seal<span class="visually-hidden"> — {theme}</span></h3>
  <p class="note">
    One original mark. A lantern, laurel, stars, two rings and the app's own words — no crest, no
    monogram, no house iconography. It carries its own ground, so it sits on either theme unchanged.
  </p>
  <div class="row seals">
    <img src="/seal.svg" width="112" height="112" alt="The Ministry of Herbology seal" />
    <img src="/favicon.svg" width="56" height="56" alt="The same mark as the app icon" />
    <img src="/favicon.svg" width="32" height="32" alt="" />
  </div>
</section>

<section aria-labelledby="{theme}-rows" class="group">
  <h3 id="{theme}-rows">Cards and list rows<span class="visually-hidden"> — {theme}</span></h3>
  <Card themed="The Register" plain="Inventory" level={4}>
    <div class="stack">
      {#each SAMPLE_SPECIMENS as specimen (specimen.id)}
        <ListRow
          themed={specimen.themed}
          plain={specimen.plain}
          meta={specimen.meta}
          icon={specimen.icon}
          href="#gallery"
        />
      {/each}
      <ListRow plain="Selected row" meta="Tapped for a batch action" icon="leaf" selected />
      <ListRow
        plain="Unavailable row"
        meta="Nothing to open yet"
        icon="leaf"
        disabled
        onclick={() => {}}
      />
    </div>
  </Card>
</section>

<section aria-labelledby="{theme}-fields" class="group">
  <h3 id="{theme}-fields">Fields<span class="visually-hidden"> — {theme}</span></h3>
  <div class="stack">
    <SearchInput
      bind:value={query}
      themed="Consult the Register"
      plain="Search specimens — {theme}"
      placeholder="Basil, north bed, toxic…"
    />
    <TextField
      bind:value={nickname}
      themed="What you call it"
      plain="Nickname"
      hint="Only you see this."
    />
    <NumberField bind:value={potSize} plain="Pot diameter" suffix="mm" min={0} step={10} />
    <SelectField
      bind:value={location}
      themed="Where it stands"
      plain="Location"
      options={SAMPLE_LOCATIONS}
    />
    <TextField plain="Field note" rows={2} placeholder="Leaf tips browning on the south side…" />
    <TextField
      plain="Species"
      error="No match in the accepted names. Try the botanical name."
      required
    />
    <Toggle
      bind:checked={notify}
      themed="Send word by owl"
      plain="Notify me about this plant"
      hint="Uses your hub notifications."
    />
  </div>
</section>

<section aria-labelledby="{theme}-who" class="group">
  <h3 id="{theme}-who">Who is acting<span class="visually-hidden"> — {theme}</span></h3>
  <p class="note">
    one shared sign-in, and the person is picked at the moment of the act. Native radios, so arrow
    keys move between them; the choice is a filled face, a tick and a sentence, never a hue. This
    one does not write to the device — the real one remembers the last choice.
  </p>
  <div class="stack">
    <MemberPicker members={SAMPLE_MEMBERS} bind:value={actingAs} remember={false} />
    <MemberPicker
      members={SAMPLE_MEMBERS}
      themed="Whose eyes"
      plain="Who saw it"
      hint="Recorded against this person. The app remembers your last choice on this device."
      remember={false}
    />
    <MemberPicker members={[]} remember={false} />
    <MemberPicker members={SAMPLE_MEMBERS} value="member-1" disabled remember={false} />
  </div>
</section>

<section aria-labelledby="{theme}-states" class="group">
  <h3 id="{theme}-states">
    Empty, loading and stale<span class="visually-hidden"> — {theme}</span>
  </h3>
  <div class="stack">
    <EmptyState
      themed="The bed lies fallow"
      plain="No specimens here yet"
      body="Nothing has been planted in this zone. Add one and it will appear in the Register."
    >
      {#snippet action()}
        <Button plain="Add a specimen" icon="plus" />
      {/snippet}
    </EmptyState>
    <Card plain="Loading" level={4}>
      <Skeleton lines={3} plain="Loading the Register…" />
    </Card>
    <StaleNotice
      themed="The owl has not returned"
      plain="The Almanac forecast"
      asOf={new Date(Date.now() - 3 * 60 * 60 * 1000)}
      reason="The weather service could not be reached on this network."
      onretry={() => {}}
    />
    <StaleNotice plain="Soil moisture" asOf={null} reason="No sensor has reported yet." />
  </div>
</section>

<section aria-labelledby="{theme}-dialog" class="group">
  <h3 id="{theme}-dialog">Dialog and sheet<span class="visually-hidden"> — {theme}</span></h3>
  <Button variant="quiet" plain="Open the sheet" onclick={() => (dialogOpen = true)} />
  <Dialog
    bind:open={dialogOpen}
    themed="Uproot this specimen?"
    plain="Remove this plant"
    description="Its logs and photos go with it. This cannot be undone."
  >
    <p>Focus is held inside this sheet, Escape closes it, and it goes back where it came from.</p>
    <TextField plain="Type the nickname to confirm" />
    {#snippet footer()}
      <Button variant="quiet" plain="Keep it" onclick={() => (dialogOpen = false)} />
      <Button variant="destructive" plain="Remove it" onclick={() => (dialogOpen = false)} />
    {/snippet}
  </Dialog>
</section>

<section aria-labelledby="{theme}-icons" class="group">
  <h3 id="{theme}-icons">Icons<span class="visually-hidden"> — {theme}</span></h3>
  <ul class="icons">
    {#each ICON_NAMES as name (name)}
      <li><Icon {name} size={22} /><span>{ICONS[name].plain}</span></li>
    {/each}
  </ul>
</section>

<section aria-labelledby="{theme}-theme" class="group">
  <h3 id="{theme}-theme">Theme switcher<span class="visually-hidden"> — {theme}</span></h3>
  <p class="note">This one writes to the whole document, not to this panel.</p>
  <ThemeSwitcher />
</section>

<style>
  .pane-title {
    margin: 0 0 var(--moh-space-4);
    font-size: var(--moh-text-lg);
    color: var(--moh-ink-muted);
    text-transform: lowercase;
    letter-spacing: 0.04em;
  }
  .group {
    margin-bottom: var(--moh-space-8);
  }
  h3 {
    font-size: var(--moh-text-base);
    margin-bottom: var(--moh-space-2);
    padding-bottom: var(--moh-space-1);
    border-bottom: 1px solid var(--moh-border);
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--moh-space-2);
    margin-bottom: var(--moh-space-2);
  }
  .stack {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-3);
  }
  hr {
    border: none;
    border-top: 1px solid var(--moh-border);
    margin: var(--moh-space-2) 0;
  }
  .icons {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(8rem, 1fr));
    gap: var(--moh-space-2);
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .icons li {
    display: flex;
    align-items: center;
    gap: var(--moh-space-2);
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }
  .note {
    margin: 0 0 var(--moh-space-2);
    max-width: 60ch;
    color: var(--moh-ink-muted);
    font-family: var(--moh-font-ui);
    font-size: var(--moh-text-sm);
  }
  .brass {
    display: flex;
    flex-direction: column;
    gap: var(--moh-space-2);
    list-style: none;
    padding: 0;
    margin: 0;
    font-size: var(--moh-text-sm);
  }
  .brass li {
    display: flex;
    align-items: center;
    gap: var(--moh-space-3);
  }
  .chip {
    flex: none;
    width: 2.5rem;
    height: 1.5rem;
    border: 1px solid var(--moh-gold-line);
    border-radius: var(--moh-radius);
  }
  .swatch-ink code {
    font-family: var(--moh-font-mono);
    font-size: var(--moh-text-xs);
  }
  .seals {
    align-items: flex-end;
  }
</style>
