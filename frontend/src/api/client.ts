const API_BASE_PATH = "/api";

interface ErrorDetail {
  code: string;
  message: string;
}

interface ErrorResponse {
  detail: ErrorDetail;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export class ApiProtocolError extends ApiError {
  constructor(status: number, message: string) {
    super(status, "protocol_error", message);
    this.name = "ApiProtocolError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  if (!isRecord(value) || !isRecord(value.detail)) {
    return false;
  }

  return (
    typeof value.detail.code === "string" &&
    value.detail.code.length > 0 &&
    typeof value.detail.message === "string" &&
    value.detail.message.length > 0
  );
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch (error) {
    if (error instanceof SyntaxError || error instanceof TypeError) {
      throw new ApiProtocolError(
        response.status,
        "API response was not valid JSON",
      );
    }
    throw error;
  }
}

export async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");

  const response = await fetch(`${API_BASE_PATH}${normalizedPath}`, {
    ...init,
    headers,
  });

  const payload = await readJson(response);
  if (!response.ok) {
    if (!isErrorResponse(payload)) {
      throw new ApiProtocolError(
        response.status,
        "API error response did not match the error protocol",
      );
    }
    throw new ApiError(
      response.status,
      payload.detail.code,
      payload.detail.message,
    );
  }

  return payload as T;
}
