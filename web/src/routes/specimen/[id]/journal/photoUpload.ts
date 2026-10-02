/** Sending a photograph to the inventory API's `POST /specimens/{id}/photos`, and what to say
 *  when the server refuses it.
 *
 *  The server judges the format from the bytes, not from the file name or the
 *  browser's guess, so this module does not second-guess it: the file input
 *  *suggests* PNG and JPEG, and whatever is picked is sent. A 415 or a 413
 *  comes back with a sentence written for a person, and that sentence is shown
 *  as given. A 503 is a deployment fact — nowhere to keep photographs — and is
 *  said as one.
 */

import { BASE, type Fetcher } from '../../../shared/http';
import type { Photo } from '../api';

export interface UploadInput {
  file: File;
  caption: string;
  memberId: string;
}

export class UploadRefused extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'UploadRefused';
  }
}

/** The form fields, the optional ones left out when empty. */
export function uploadForm(input: UploadInput): FormData {
  const form = new FormData();
  form.append('file', input.file, input.file.name || 'photograph');
  const caption = input.caption.trim();
  if (caption) form.append('caption', caption);
  if (input.memberId) form.append('member_id', input.memberId);
  return form;
}

/** What a refusal means, in a sentence. `detail` is the server's own words. */
export function refusalSentence(status: number, detail: string | null): string {
  if (status === 415 || status === 413 || status === 507)
    return (
      detail ||
      (status === 415
        ? 'The server would not accept that file as a photograph.'
        : 'That file is too large to keep.')
    );
  if (status === 503)
    return (
      'Photographs cannot be kept yet: whoever runs this installation has not given the ' +
      'Ministry a place to store them.' +
      (detail ? ` For the operator: ${detail}` : '')
    );
  if (status === 404)
    return 'This plant is no longer in the Register, so the photograph has nowhere to go.';
  if (status === 422)
    return detail || 'The server would not accept that — something in the form was not valid.';
  return detail
    ? `The greenhouse answered with an error (${status}): ${detail}`
    : `The greenhouse answered with an error (${status}).`;
}

async function detailOf(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === 'string' ? body.detail : null;
  } catch {
    return null;
  }
}

export async function uploadPhoto(
  specimenId: string,
  input: UploadInput,
  fetcher: Fetcher,
): Promise<Photo> {
  const response = await fetcher(`${BASE}/specimens/${encodeURIComponent(specimenId)}/photos`, {
    method: 'POST',
    headers: { accept: 'application/json' },
    body: uploadForm(input),
  });
  if (!response.ok) {
    throw new UploadRefused(
      response.status,
      refusalSentence(response.status, await detailOf(response)),
    );
  }
  return (await response.json()) as Photo;
}
