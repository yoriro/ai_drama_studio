import { ApiError } from "../api";

export function describeApiError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error && error.message.length > 0) {
    return error.message;
  }
  if (typeof error === "string" && error.length > 0) {
    return error;
  }
  if (error !== null && error !== undefined) {
    return String(error);
  }
  return "请求失败";
}

function apiErrorCode(error: unknown): string | null {
  return error instanceof ApiError ? error.code : null;
}

interface ApiErrorMessageProps {
  error: unknown;
}

export function ApiErrorMessage({ error }: ApiErrorMessageProps) {
  const code = apiErrorCode(error);
  return (
    <p className="error-message" role="alert">
      <span className="error-message-text">{describeApiError(error)}</span>
      {code !== null && (
        <span className="error-message-code">code: {code}</span>
      )}
    </p>
  );
}
