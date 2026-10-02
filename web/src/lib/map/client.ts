/** Talking to `/grounds`.
 *
 * `$api/client` is the design system's and is read-only; the Grounds writes, and
 * the writes are the part where the error body matters. This endpoint answers
 * 413, 415, 422, 503 and 507, and every one of those carries a `detail`
 * written to be read by the person who hit it — "the volume holding map
 * layers is full", "set MOH_GROUNDS_IMAGE_DIR". Throwing away the body and
 * showing "Request failed" would throw away the only useful half.
 *
 * So `GroundsError` keeps the status and the detail, and every surface in
 * this directory shows the detail verbatim.
 */

import type { Calibration, MapLayer, Pin, PixelPoint, Zone } from './types';

const BASE = '/api/v1';

export class GroundsError extends Error {
  readonly status: number;
  /** The server's own sentence, or a plain one if it sent none. */
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'GroundsError';
    this.status = status;
    this.detail = detail;
  }
}

/** Whether the failure is something the operator fixes rather than the user.
 *
 * 503 means no volume is configured and 507 means it is full — neither is
 * anything the person holding the phone can do about, and both deserve
 * different words from "that file is not a PNG".
 */
export function isOperatorProblem(error: unknown): boolean {
  return error instanceof GroundsError && (error.status === 503 || error.status === 507);
}

async function fail(response: Response, path: string): Promise<never> {
  let detail = `${response.status} ${response.statusText} for ${path}`;
  try {
    const body = await response.json();
    if (typeof body?.detail === 'string') detail = body.detail;
    else if (Array.isArray(body?.detail) && body.detail[0]?.msg) {
      detail = String(body.detail[0].msg);
    }
  } catch {
    // A non-JSON error body is the proxy's, not the API's. Keep the status line.
  }
  throw new GroundsError(response.status, detail);
}

async function request<T>(path: string, init: RequestInit, fetcher: typeof fetch): Promise<T> {
  const response = await fetcher(`${BASE}${path}`, init);
  if (!response.ok) await fail(response, path);
  return (await response.json()) as T;
}

export function listLayers(fetcher: typeof fetch = fetch): Promise<MapLayer[]> {
  return request<MapLayer[]>(
    '/grounds/layers',
    { headers: { accept: 'application/json' } },
    fetcher,
  );
}

export function listPins(layerId?: string, fetcher: typeof fetch = fetch): Promise<Pin[]> {
  const query = layerId ? `?layer_id=${encodeURIComponent(layerId)}` : '';
  return request<Pin[]>(
    `/grounds/pins${query}`,
    { headers: { accept: 'application/json' } },
    fetcher,
  );
}

export function setPin(
  pin: { specimen_id: string; layer_id: string; px: PixelPoint | null },
  fetcher: typeof fetch = fetch,
): Promise<Pin> {
  return request<Pin>(
    '/grounds/pins',
    {
      method: 'PUT',
      headers: { 'content-type': 'application/json', accept: 'application/json' },
      body: JSON.stringify(pin),
    },
    fetcher,
  );
}

export function setCalibration(
  layerId: string,
  calibration: Partial<Calibration>,
  fetcher: typeof fetch = fetch,
): Promise<MapLayer> {
  return request<MapLayer>(
    `/grounds/layers/${encodeURIComponent(layerId)}/calibration`,
    {
      method: 'PUT',
      headers: { 'content-type': 'application/json', accept: 'application/json' },
      body: JSON.stringify(calibration),
    },
    fetcher,
  );
}

export function uploadLayer(
  input: { file: File; name: string; kind: 'floor_plan' | 'survey'; siteId?: string },
  fetcher: typeof fetch = fetch,
): Promise<MapLayer> {
  const form = new FormData();
  form.append('file', input.file);
  form.append('name', input.name);
  form.append('kind', input.kind);
  if (input.siteId) form.append('site_id', input.siteId);
  // No `content-type` header: the browser has to set the multipart boundary.
  return request<MapLayer>(
    '/grounds/layers',
    { method: 'POST', body: form, headers: { accept: 'application/json' } },
    fetcher,
  );
}

/** Zones are locations with a boundary, and locations are the inventory API's.
 *
 * The map reads them from `GET /locations` and draws them. It cannot write
 * one back: `LocationCreate`, which is the body of `PATCH /locations/{id}`,
 * declares no `boundary_px`. See the README — escalated, not worked around.
 */
export async function listZones(layerId?: string, fetcher: typeof fetch = fetch): Promise<Zone[]> {
  const locations = await request<Zone[]>(
    '/locations',
    { headers: { accept: 'application/json' } },
    fetcher,
  );
  return locations.filter(
    (location) =>
      Array.isArray(location.boundary_px) &&
      location.boundary_px.length >= 3 &&
      (!layerId || location.map_layer_id === layerId),
  );
}
