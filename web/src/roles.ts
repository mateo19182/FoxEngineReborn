/** Roles that may upload data, run ingest, and create tags (not delete). */
export function canIngest(roles: string[]): boolean {
  return roles.some((r) => r === "admin" || r === "operator" || r === "manager");
}
