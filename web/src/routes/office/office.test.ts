import { describe, expect, it } from 'vitest';
import {
  createdFeed,
  feedBody,
  filterSummary,
  integrationView,
  listedFeed,
  setupStep,
  sortFeeds,
  sortIntegrations,
  type CalendarFeedResponse,
  type Integration,
} from './office';

const NOW = new Date('2026-10-02T12:00:00Z');
const row = (over: Partial<Integration>): Integration => ({
  id: 'i1',
  kind: 'home_assistant',
  name: 'Home Assistant',
  enabled: true,
  ...over,
});

describe('integration status, in words', () => {
  it('ok says when it was last heard from', () => {
    const v = integrationView(row({ status: 'ok', last_ok_at: '2026-10-02T11:50:00Z' }), NOW);
    expect(v).toMatchObject({
      word: 'Answering',
      tone: 'ok',
      detail: 'Last heard from 10 minutes ago.',
    });
  });

  it('down shows the upstream error as given', () => {
    const v = integrationView(
      row({ status: 'down', last_error: 'Connection refused', last_ok_at: null }),
      NOW,
    );
    expect(v).toMatchObject({ word: 'Not answering', tone: 'warn', error: 'Connection refused' });
    expect(v.detail).toBe('It has never answered.');
  });

  it('degraded is answering with errors', () => {
    const v = integrationView(
      row({
        status: 'degraded',
        last_error: '1 entity unavailable',
        last_ok_at: '2026-10-02T11:00:00Z',
      }),
      NOW,
    );
    expect(v.word).toBe('Answering, with errors');
    expect(v.error).toBe('1 entity unavailable');
  });

  it('stale with a last success is "gone quiet"; with none it is "never heard from"', () => {
    expect(
      integrationView(row({ status: 'stale', last_ok_at: '2026-10-02T06:00:00Z' }), NOW),
    ).toMatchObject({
      word: 'Gone quiet',
      tone: 'warn',
    });
    expect(integrationView(row({ status: 'stale', last_ok_at: null }), NOW)).toMatchObject({
      word: 'Never heard from',
      detail: 'Configured, but it has not answered once yet.',
    });
  });

  it('unconfigured is a setup step, never a warning, and says what to set', () => {
    const v = integrationView(row({ status: 'unconfigured' }), NOW);
    expect(v.tone).toBe('setup');
    expect(v.word).toBe('Not set up');
    expect(v.detail).toMatch(/MOH_HA_BASE_URL/);
    expect(v.error).toBeNull();
    expect(setupStep('ecowitt')).toMatch(/deployment guide/);
    expect(setupStep('mqtt')).toMatch(/MOH_MQTT_HOST.*aiomqtt/);
  });

  it('a status the screen does not know is shown as itself, not guessed at', () => {
    expect(integrationView(row({ status: 'unknown' }), NOW).word).toBe('unknown');
    expect(integrationView(row({ status: undefined }), NOW).word).toBe('Status not reported');
  });

  it('a switched-off integration is not a fault', () => {
    expect(integrationView(row({ enabled: false, status: 'down' }), NOW).tone).toBe('off');
  });

  it('lists what needs attention first, then setup steps', () => {
    const sorted = sortIntegrations(
      [
        row({ id: 'a', name: 'A', status: 'ok' }),
        row({ id: 'b', name: 'B', status: 'unconfigured' }),
        row({ id: 'c', name: 'C', status: 'down' }),
      ],
      NOW,
    );
    expect(sorted.map((r) => r.id)).toEqual(['c', 'b', 'a']);
  });
});

describe('a feed URL is a password', () => {
  const TOKEN = 'q7khYikxgPUNxs1R9skU81BQ4c7hXRPYSBmsLnhvXyg';
  const response: CalendarFeedResponse = {
    id: 'f1',
    member_id: 'm1',
    name: 'All rounds',
    webcal_url: `webcal://example/api/v1/calendar/${TOKEN}.ics`,
    https_url: `https://example/api/v1/calendar/${TOKEN}.ics`,
    filters: { outdoor: true, task_types: ['water'] },
    push_target: 'none',
    last_rendered_at: null,
    revoked: false,
  };

  it('a listed feed carries no URL and no token, however it is serialised', () => {
    const listed = listedFeed(response);
    const json = JSON.stringify(listed);
    expect(json).not.toContain(TOKEN);
    expect(json).not.toContain('webcal');
    expect(json).not.toContain('https://');
    expect(Object.keys(listed).sort()).toEqual(
      ['filters', 'id', 'last_rendered_at', 'member_id', 'name', 'revoked'].sort(),
    );
  });

  it('a URL field the API adds later is left out too', () => {
    const later = { ...response, ics_url: `https://x/${TOKEN}.ics` } as CalendarFeedResponse;
    expect(JSON.stringify(listedFeed(later))).not.toContain(TOKEN);
  });

  it('the created feed is the one place the URL is kept', () => {
    expect(createdFeed(response)).toEqual({
      id: 'f1',
      name: 'All rounds',
      webcal_url: response.webcal_url,
      https_url: response.https_url,
    });
  });

  it('revoked feeds list last', () => {
    const a = listedFeed({ ...response, id: 'a', name: 'A', revoked: true });
    const b = listedFeed({ ...response, id: 'b', name: 'B' });
    expect(sortFeeds([a, b]).map((f) => f.id)).toEqual(['b', 'a']);
  });
});

describe('feed filters', () => {
  it('summarises what a feed carries', () => {
    expect(filterSummary({})).toBe('every plant · every kind of task');
    expect(
      filterSummary(
        { outdoor: true, task_types: ['water', 'cover'], location_ids: ['l1'] },
        () => 'South Border',
      ),
    ).toBe('outdoor plants · Water, Cover against frost · at South Border');
  });

  it('sends only the filters that were chosen', () => {
    expect(feedBody({ name: ' Phone ', memberId: 'm1', outdoor: '', taskTypes: [] })).toEqual({
      member_id: 'm1',
      name: 'Phone',
      filters: {},
    });
    expect(
      feedBody({ name: 'Out', memberId: 'm1', outdoor: 'false', taskTypes: ['mist'] }).filters,
    ).toEqual({
      outdoor: false,
      task_types: ['mist'],
    });
  });
});
