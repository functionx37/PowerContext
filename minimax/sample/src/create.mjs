export function createTicket(id, title) {
  if (typeof title !== 'string' || !title.trim()) throw new RangeError('Title required');
  return { id, title: title.trim(), status: 'open', tags: [], archived: false };
}
