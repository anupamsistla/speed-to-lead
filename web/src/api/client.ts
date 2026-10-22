import createClient from "openapi-fetch";
import type { paths } from "./schema";

/** Typed client generated from the FastAPI OpenAPI schema (web/openapi.json). */
export const api = createClient<paths>({ baseUrl: "" });

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function messageFrom(error: unknown, status: number): string {
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
        .filter(Boolean)
        .join("; ");
    }
    if (detail && typeof detail === "object" && "problems" in detail) {
      return (detail as { problems: string[] }).problems.join("; ");
    }
  }
  return `Request failed (${status})`;
}

/** Unwrap an openapi-fetch result, throwing ApiError with the server's explanation. */
export async function unwrap<T>(
  p: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let res;
  try {
    res = await p;
  } catch {
    throw new ApiError(0, "Cannot reach the API. Is the server running?");
  }
  if (res.error !== undefined || res.data === undefined) {
    throw new ApiError(res.response.status, messageFrom(res.error, res.response.status));
  }
  return res.data;
}
