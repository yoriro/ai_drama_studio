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

export type JsonResponseParser<T> = (value: unknown, status: number) => T;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function protocolError(status: number, message: string): never {
  throw new ApiProtocolError(status, message);
}

export function requireObjectWithKeys(
  value: unknown,
  requiredKeys: readonly string[],
  optionalKeys: readonly string[],
  status: number,
  context: string,
): Record<string, unknown> {
  if (!isRecord(value)) {
    return protocolError(status, `${context} must be an object`);
  }

  const allowedKeys = new Set([...requiredKeys, ...optionalKeys]);
  const hasAllRequiredKeys = requiredKeys.every((key) =>
    Object.prototype.hasOwnProperty.call(value, key),
  );
  const hasOnlyAllowedKeys = Object.keys(value).every((key) =>
    allowedKeys.has(key),
  );
  if (!hasAllRequiredKeys || !hasOnlyAllowedKeys) {
    return protocolError(status, `${context} has an invalid field set`);
  }
  return value;
}

export function requireArray(
  value: unknown,
  status: number,
  context: string,
): unknown[] {
  if (!Array.isArray(value)) {
    return protocolError(status, `${context} must be an array`);
  }
  return value;
}

export function requireString(
  value: unknown,
  status: number,
  context: string,
): string {
  if (typeof value !== "string") {
    return protocolError(status, `${context} must be a string`);
  }
  return value;
}

export function requireNullableString(
  value: unknown,
  status: number,
  context: string,
): string | null {
  if (value !== null && typeof value !== "string") {
    return protocolError(status, `${context} must be a string or null`);
  }
  return value;
}

export function requireBoolean(
  value: unknown,
  status: number,
  context: string,
): boolean {
  if (typeof value !== "boolean") {
    return protocolError(status, `${context} must be a boolean`);
  }
  return value;
}

export function requirePositiveSafeInteger(
  value: unknown,
  context: string,
  status = 0,
): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value <= 0) {
    return protocolError(
      status,
      `${context} must be a positive JavaScript safe integer`,
    );
  }
  return value;
}

export function requireNonNegativeSafeInteger(
  value: unknown,
  context: string,
  status: number,
): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    return protocolError(
      status,
      `${context} must be a non-negative JavaScript safe integer`,
    );
  }
  return value;
}

export function requireFiniteNumber(
  value: unknown,
  context: string,
  status: number,
): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return protocolError(status, `${context} must be a finite number`);
  }
  return value;
}

export function requireEnum<T extends string>(
  value: unknown,
  allowed: readonly T[],
  context: string,
  status: number,
): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    return protocolError(status, `${context} has an unknown value`);
  }
  return value as T;
}

const MAX_SIGNED_64_BIT = BigInt("9223372036854775807");
const MAX_SAFE_INTEGER_BIGINT = BigInt(Number.MAX_SAFE_INTEGER);

export function requireDecimalSeed(
  value: unknown,
  context: string,
  status: number,
): string {
  if (typeof value !== "string" || !/^\d+$/.test(value)) {
    return protocolError(
      status,
      `${context} must be a decimal string in 0..2^63-1`,
    );
  }
  if (BigInt(value) > MAX_SIGNED_64_BIT) {
    return protocolError(
      status,
      `${context} must be a decimal string in 0..2^63-1`,
    );
  }
  return value;
}

export function requirePositiveSafeIntegerText(
  value: string,
  context: string,
  status: number,
): string {
  if (!/^[1-9]\d*$/.test(value) || BigInt(value) > MAX_SAFE_INTEGER_BIGINT) {
    return protocolError(
      status,
      `${context} must identify a positive JavaScript safe integer`,
    );
  }
  return value;
}

export function requireNullableObject(
  value: unknown,
  status: number,
  context: string,
): Record<string, unknown> | null {
  if (value === null) {
    return null;
  }
  if (!isRecord(value)) {
    return protocolError(status, `${context} must be an object or null`);
  }
  return value;
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

async function throwApiError(response: Response): Promise<never> {
  const payload = await readJson(response);
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

export async function requestJson<T>(
  path: string,
  init?: RequestInit,
  parse?: JsonResponseParser<T>,
): Promise<T> {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");

  const response = await fetch(`${API_BASE_PATH}${normalizedPath}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    return await throwApiError(response);
  }

  const payload = await readJson(response);
  return parse === undefined ? (payload as T) : parse(payload, response.status);
}

export async function requestNoContent(
  path: string,
  init?: RequestInit,
): Promise<void> {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");

  const response = await fetch(`${API_BASE_PATH}${normalizedPath}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    await throwApiError(response);
  }
  if (response.status !== 204) {
    throw new ApiProtocolError(response.status, "Expected a 204 response");
  }
}
