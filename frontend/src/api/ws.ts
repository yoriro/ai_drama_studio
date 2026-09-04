import { parseTaskEventResponse } from "./tasks";
import type { TaskEvent } from "./tasks";

export function buildWebSocketUrl(
  path: string,
  pageLocation: Location = window.location,
): string {
  const url = new URL(path, pageLocation.origin);
  url.protocol = pageLocation.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export function openWebSocket(
  path: string,
  pageLocation: Location = window.location,
): WebSocket {
  return new WebSocket(buildWebSocketUrl(path, pageLocation));
}

export function openTaskWebSocket(
  pageLocation: Location = window.location,
): WebSocket {
  return openWebSocket("/ws/tasks", pageLocation);
}

export function parseTaskEvent(data: string): TaskEvent {
  const value: unknown = JSON.parse(data);
  return parseTaskEventResponse(value, 0);
}

export function closeWebSocket(socket: WebSocket): void {
  socket.close();
}
