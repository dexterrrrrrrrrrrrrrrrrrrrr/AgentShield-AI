import { protectedApi } from "./protected-api";

export function agentApi(path: string, method = "GET", body?: unknown) {
  return protectedApi(`/agent${path}`, method, body);
}
