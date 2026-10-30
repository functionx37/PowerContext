/** Ticket query module. Input is an in-memory snapshot supplied by the caller. */
export function listTickets(tickets, options = {}) {
  const { status, tag, limit } = options;
  if (status && !['open', 'in_progress', 'closed'].includes(status)) {
    throw new RangeError('Invalid status');
  }
  if (limit !== undefined && (!Number.isInteger(limit) || limit < 0)) {
    throw new RangeError('Invalid limit');
  }
  const result = tickets.filter(ticket =>
    (!status || ticket.status === status) &&
    (tag === undefined || ticket.tags.includes(tag))
  );
  return limit === undefined ? result : result.slice(0, limit);
}
