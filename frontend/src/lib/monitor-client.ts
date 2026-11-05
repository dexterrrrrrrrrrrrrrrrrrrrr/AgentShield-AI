import { protectedApi } from "./protected-api";

export function monitoringApi(path: string, body?: unknown) {
  return protectedApi(path, body === undefined ? "GET" : "POST", body);
}
