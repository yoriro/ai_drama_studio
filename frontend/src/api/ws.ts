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

export function closeWebSocket(socket: WebSocket): void {
  socket.close();
}
