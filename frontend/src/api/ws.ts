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
  return JSON.parse(data) as TaskEvent;
}

export function closeWebSocket(socket: WebSocket): void {
  socket.close();
}
