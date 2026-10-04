/** Include off-page selections for backend validation, but skip known completed logs. */
export function getTerminableLogIds(
  selectedIds: ReadonlySet<string>,
  logs: ReadonlyArray<{ id: string; status: string }>,
): string[] {
  const statuses = new Map(logs.map(log => [log.id, log.status]));
  return Array.from(selectedIds).filter(id => !statuses.has(id) || statuses.get(id) === 'pending');
}
