/**
 * Chunked upload client.
 *
 * Cloudflare refuses a single request body over 100 MB on Free/Pro, so the
 * whole file cannot go up as one multipart POST once it is bigger than that.
 * This splits it into `part_size` pieces (advertised by the API, 64 MiB by
 * default) and appends them in order. Everything below the proxy stays exactly
 * as it was: same plan gates, same 201 response, same detail objects.
 *
 * The server keeps the bytes received, so a failed part is retried from the
 * server's own resume point rather than from the client's idea of progress.
 */

export type QuotaDetail = {
  error: string;
  message?: string;
  limit_bytes?: number;
  size_bytes?: number;
  resets_at?: string | null;
  [key: string]: unknown;
};

export class UploadError extends Error {
  status: number;
  detail: QuotaDetail | null;

  constructor(status: number, message: string, detail: QuotaDetail | null = null) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

type InitResponse = {
  upload_id: string;
  part_size: number;
  next_index: number;
  received_bytes: number;
};

const MAX_PART_RETRIES = 3;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function safeJson(text: string): any {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function toError(status: number, text: string): UploadError {
  const body = safeJson(text);
  const d = body?.detail;
  if (d && typeof d === "object" && d.error) {
    return new UploadError(status, d.message || `upload failed (${status})`, d as QuotaDetail);
  }
  const msg = typeof d === "string" ? d : `upload failed (${status})`;
  return new UploadError(status, msg, null);
}

async function jsonFetch(url: string, init: RequestInit): Promise<{ status: number; text: string }> {
  const r = await fetch(url, init);
  return { status: r.status, text: await r.text() };
}

/** One part, streamed by XHR so the progress bar reflects real bytes on the wire. */
function sendPart(
  url: string,
  token: string,
  blob: Blob,
  onBytes: (loaded: number) => void,
): Promise<{ status: number; text: string }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (ev) => ev.lengthComputable && onBytes(ev.loaded);
    xhr.onload = () => resolve({ status: xhr.status, text: xhr.responseText });
    xhr.onerror = () => reject(new Error("network"));
    xhr.onabort = () => reject(new Error("aborted"));
    xhr.send(blob);
  });
}

export async function uploadVideoChunked(
  file: File,
  token: string,
  onProgress: (pct: number) => void,
): Promise<any> {
  const auth = { Authorization: `Bearer ${token}` };

  // 1. allowance and size are checked here, before a byte leaves the browser
  const init = await jsonFetch("/api/videos/upload/init", {
    method: "POST",
    headers: { ...auth, "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name, size_bytes: file.size }),
  });
  if (init.status !== 201) throw toError(init.status, init.text);

  const { upload_id, part_size, next_index, received_bytes } = JSON.parse(init.text) as InitResponse;
  const total = file.size;
  let index = next_index ?? 0;
  let sent = received_bytes ?? 0;

  const pct = (bytes: number) => onProgress(total ? Math.min(99, Math.round((bytes / total) * 100)) : 0);
  pct(sent);

  const abort = async () => {
    try {
      await fetch(`/api/videos/upload/${upload_id}`, { method: "DELETE", headers: auth });
    } catch {
      /* the server sweeps abandoned sessions after 24 h anyway */
    }
  };

  // 2. parts, in order; the server rejects anything out of sequence
  while (sent < total) {
    const start = index * part_size;
    const end = Math.min(start + part_size, total);
    const blob = file.slice(start, end);
    let attempt = 0;
    let resync = false;

    for (;;) {
      try {
        const r = await sendPart(
          `/api/videos/upload/${upload_id}/part/${index}`,
          token,
          blob,
          (loaded) => pct(start + loaded),
        );
        if (r.status === 200) {
          sent = end;
          index += 1;
          break;
        }
        const body = safeJson(r.text);
        const detail = body?.detail;
        // the server knows what it actually has - follow it, do not argue
        if (r.status === 409 && detail && typeof detail.next_index === "number") {
          index = detail.next_index;
          sent = typeof detail.received_bytes === "number" ? detail.received_bytes : index * part_size;
          resync = true;
          break;
        }
        throw toError(r.status, r.text);
      } catch (e) {
        if (e instanceof UploadError) {
          await abort();
          throw e;
        }
        attempt += 1;
        if (attempt >= MAX_PART_RETRIES) {
          await abort();
          throw new UploadError(0, "network error during upload - try again", null);
        }
        await sleep(400 * attempt);
      }
    }

    if (resync) continue;
  }

  // 3. assemble + length probe happen server-side; 422 means "too long for your plan"
  const done = await jsonFetch(`/api/videos/upload/${upload_id}/complete`, {
    method: "POST",
    headers: auth,
  });
  if (done.status !== 201) throw toError(done.status, done.text);

  onProgress(100);
  return JSON.parse(done.text);
}
