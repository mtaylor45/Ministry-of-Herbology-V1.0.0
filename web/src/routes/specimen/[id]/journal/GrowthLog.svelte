<script lang="ts">
  /** The photo growth log: this plant's photographs, oldest first.
   *
   *  `GET /specimens/{id}/photos`, and since the inventory API's change `POST` as well: given a
   *  `specimenId`, the log carries the upload control under it. Uploads have
   *  no thumbnail in 1.x, so each picture is `thumb_url ?? url`.
   *
   *  Each photograph is a `<figure>` with real alt text and a `<time>`, so the
   *  log reads in order without the pictures. The Register's chosen portrait is
   *  said in words beside its date rather than by a colour or a border alone
   *.
   */
  import { Card, EmptyState, StaleNotice, type Member } from '$ui';
  import PhotoUpload from './PhotoUpload.svelte';
  import { formatDate } from '../labels';
  import {
    FIRST_PHOTO,
    growthLogSentence,
    oldestFirst,
    photoAlt,
    type Photo,
  } from './journalFacet';

  let {
    photos,
    specimenName,
    error = null,
    specimenId,
    members = [],
    onuploaded,
  }: {
    photos: Photo[];
    specimenName: string;
    error?: string | null;
    /** Given, the upload control is shown. */
    specimenId?: string;
    members?: Member[];
    onuploaded?: () => void;
  } = $props();

  const ordered = $derived(oldestFirst(photos));
  const summary = $derived(
    growthLogSentence(
      ordered.length,
      formatDate(ordered[0]?.taken_at, 'an unrecorded date'),
      formatDate(ordered[ordered.length - 1]?.taken_at, 'an unrecorded date'),
    ),
  );
</script>

<Card themed="How it has grown" plain="Photo growth log, oldest first" level={2}>
  {#if error}
    <StaleNotice plain="The photograph list" asOf={null} reason={error} />
  {:else if ordered.length}
    <p class="summary">{summary}</p>
    <ol class="log">
      {#each ordered as photo (photo.id)}
        {@const when = formatDate(photo.taken_at, 'an unrecorded date')}
        <li>
          <figure class="entry">
            <div class="frame">
              <img
                src={photo.thumb_url ?? photo.url}
                alt={photoAlt(photo, specimenName, when)}
                loading="lazy"
                decoding="async"
              />
            </div>
            <figcaption class="caption">
              <p class="when">
                <time datetime={photo.taken_at}>{when}</time>
                {#if photo.is_primary}
                  <span aria-hidden="true">·</span>
                  <span>The Register's portrait</span>
                {/if}
              </p>
              <p class="text">
                {#if photo.caption?.trim()}
                  {photo.caption}
                {:else}
                  <span class="unrecorded">No caption</span>
                {/if}
              </p>
            </figcaption>
          </figure>
        </li>
      {/each}
    </ol>
  {:else}
    <EmptyState
      icon="camera"
      themed="No likenesses taken"
      plain="No photographs yet"
      body={specimenId ? FIRST_PHOTO : undefined}
    />
  {/if}
  {#if specimenId}
    <PhotoUpload {specimenId} {specimenName} {members} {onuploaded} />
  {/if}
</Card>

<style>
  .summary {
    margin: 0 0 var(--moh-space-4);
    color: var(--moh-ink-muted);
    font-size: var(--moh-text-sm);
  }

  .log {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--moh-space-4);
  }

  .entry {
    margin: 0;
    display: grid;
    gap: var(--moh-space-2);
  }

  /* Photographs are whatever shape the camera gave them; the frame is square
     so the log does not jump as thumbnails arrive, and the picture is kept
     whole inside it rather than cropped. */
  .frame {
    aspect-ratio: 1;
    background: var(--moh-surface-sunken);
    border: 1px solid var(--moh-gold-line);
    border-radius: var(--moh-radius);
    overflow: hidden;
    display: grid;
    place-items: center;
  }

  .frame img {
    width: 100%;
    height: 100%;
    object-fit: contain;
    display: block;
  }

  .caption {
    display: grid;
    gap: var(--moh-space-1);
  }

  .when {
    margin: 0;
    display: flex;
    gap: var(--moh-space-2);
    flex-wrap: wrap;
    font-size: var(--moh-text-sm);
    color: var(--moh-ink-muted);
  }

  .text {
    margin: 0;
    color: var(--moh-ink);
  }

  .unrecorded {
    font-style: italic;
    color: var(--moh-ink-muted);
  }

  /* Given room, the log goes two across; the order is still reading order. */
  @media (min-width: 40rem) {
    .log {
      grid-template-columns: 1fr 1fr;
    }
  }
</style>
