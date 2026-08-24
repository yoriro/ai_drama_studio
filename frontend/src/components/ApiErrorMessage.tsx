import { ApiError } from "../api";

export function describeApiError(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.code}：${error.message}`;
  }
  if (error instanceof Error && error.message.length > 0) {
    return error.message;
  }
  return "请求失败";
}

interface ApiErrorMessageProps {
  error: unknown;
}

export function ApiErrorMessage({ error }: ApiErrorMessageProps) {
  return (
    <p className="error-message" role="alert">
      {describeApiError(error)}
    </p>
  );
}
