import { describe, expect, it, vi } from 'vitest';
import { UploadRefused, refusalSentence, uploadForm, uploadPhoto } from './photoUpload';

const png = () =>
  new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], 'leaf.png', { type: 'image/png' });

describe('the upload form', () => {
  it('sends the file, and caption and member only when given', () => {
    const full = uploadForm({ file: png(), caption: ' First flower ', memberId: 'm1' });
    expect(full.get('caption')).toBe('First flower');
    expect(full.get('member_id')).toBe('m1');
    expect(full.get('file')).toBeInstanceOf(File);
    const bare = uploadForm({ file: png(), caption: '  ', memberId: '' });
    expect(bare.has('caption')).toBe(false);
    expect(bare.has('member_id')).toBe(false);
  });
});

describe('a refusal, in words', () => {
  it('shows the server’s own 415 and 413 sentences as given', () => {
    expect(refusalSentence(415, 'That is a GIF; a photograph must be PNG or JPEG.')).toBe(
      'That is a GIF; a photograph must be PNG or JPEG.',
    );
    expect(refusalSentence(413, 'Larger than 25 MiB.')).toBe('Larger than 25 MiB.');
  });

  it('says a 503 is the operator not having set a place up', () => {
    expect(refusalSentence(503, 'Set MOH_PHOTOS_IMAGE_DIR')).toMatch(
      /^Photographs cannot be kept yet: whoever runs this installation has not given the Ministry a place to store them\. For the operator: Set MOH_PHOTOS_IMAGE_DIR$/,
    );
  });

  it('reads the detail from the response and throws it', async () => {
    const fetcher = vi.fn(
      async () => new Response(JSON.stringify({ detail: 'Not a photograph.' }), { status: 415 }),
    );
    await expect(
      uploadPhoto(
        'p1',
        { file: png(), caption: '', memberId: '' },
        fetcher as unknown as typeof fetch,
      ),
    ).rejects.toEqual(new UploadRefused(415, 'Not a photograph.'));
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/specimens/p1/photos',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
