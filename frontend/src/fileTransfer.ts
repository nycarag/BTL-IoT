/**
 * Utilities for file download and upload with authorization headers.
 */

export type ApiFn = (path: string, init?: RequestInit) => Promise<Response>;

export type ImportIssue = {
  row: number;
  field: string | null;
  message: string;
};

export type ImportResult = {
  mode: "preview" | "commit";
  total_rows: number;
  valid_rows: number;
  created: number;
  updated: number;
  skipped: number;
  errors: ImportIssue[];
  rows: Record<string, unknown>[];
};

function extractFilename(disposition: string | null, fallbackName: string): string {
  if (!disposition) return fallbackName;

  // RFC 5987 / RFC 6266: filename*=UTF-8''...
  const utf8Match = disposition.match(/filename\*\s*=\s*(?:UTF-8|utf-8)''([^;\s]+)/i);
  if (utf8Match && utf8Match[1]) {
    try {
      return decodeURIComponent(utf8Match[1].replace(/["']/g, ""));
    } catch {
      // Fallback nếu giải mã URI thất bại
    }
  }

  // Định dạng tiêu chuẩn: filename="..." hoặc filename=...
  const standardMatch = disposition.match(/filename\s*=\s*(?:"([^"]+)"|([^;\s]+))/i);
  if (standardMatch) {
    const raw = standardMatch[1] || standardMatch[2];
    if (raw) return raw.trim();
  }

  return fallbackName;
}

/**
 * Downloads a file from the authenticated API endpoint.
 * Fetches the binary blob, resolves filename from Content-Disposition, and triggers browser download.
 */
export async function downloadFile(api: ApiFn, path: string, fallbackName: string): Promise<void> {
  const response = await api(path);
  if (!response.ok) {
    let message = "";
    try {
      const err = (await response.json()) as { detail?: unknown };
      if (typeof err.detail === "string") {
        message = err.detail;
      }
    } catch {
      // Bỏ qua lỗi parse JSON nếu body không phải JSON
    }
    throw new Error(message || `Yêu cầu thất bại (${response.status})`);
  }

  const disposition = response.headers.get("content-disposition");
  const filename = extractFilename(disposition, fallbackName);
  const blob = await response.blob();
  const blobUrl = URL.createObjectURL(blob);

  const anchor = document.createElement("a");
  anchor.href = blobUrl;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);

  setTimeout(() => {
    URL.revokeObjectURL(blobUrl);
  }, 0);
}

/**
 * Creates a raw API function that attaches the Bearer token without throwing on non-2xx status codes.
 */
export function makeRawApi(apiUrl: string, token: string): ApiFn {
  return async (path: string, init: RequestInit = {}): Promise<Response> => {
    const headers = new Headers(init.headers);
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    return fetch(`${apiUrl}/api${path}`, { ...init, headers });
  };
}

// Không dùng hàm api() của App.tsx cho upload vì api() tự ném Error khi gặp status 422, làm mất response body chứa danh sách lỗi ImportResult.
export async function uploadImport(
  api: ApiFn,
  path: string,
  file: File,
  fields: Record<string, string> = {}
): Promise<ImportResult> {
  const formData = new FormData();
  formData.append("file", file);
  for (const [key, value] of Object.entries(fields)) {
    formData.append(key, value);
  }

  const response = await api(path, {
    method: "POST",
    body: formData,
  });

  if (response.status === 200 || response.status === 422) {
    return (await response.json()) as ImportResult;
  }

  let errorDetail = "";
  try {
    const err = (await response.json()) as { detail?: unknown; message?: unknown };
    if (typeof err.detail === "string") {
      errorDetail = err.detail;
    } else if (Array.isArray(err.detail)) {
      errorDetail = err.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join(", ");
    } else if (typeof err.message === "string") {
      errorDetail = err.message;
    }
  } catch {
    // Body không phải JSON
  }

  throw new Error(errorDetail || `Yêu cầu thất bại (${response.status})`);
}
