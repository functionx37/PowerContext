import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { listTickets } from '../src/tickets.mjs';
import { createTicket } from '../src/create.mjs';
const tickets = JSON.parse(readFileSync(new URL('../data/tickets.json', import.meta.url)));
const ids = rows => rows.map(t => t.id);
test('R-002 original status query with explicit archived inclusion', () => {
  assert.deepEqual(ids(listTickets(tickets, { status: 'open', includeArchived: true })), ['T1', 'T2']);
});
test('R-002 combined status and tag', () => {
  assert.deepEqual(ids(listTickets(tickets, { status: 'closed', tag: 'api', includeArchived: true })), []);
});
test('R-002 empty status means no status filter', () => {
  assert.equal(listTickets(tickets, { status: '', includeArchived: true }).length, 5);
});
test('R-002 invalid status is rejected', () => {
  assert.throws(() => listTickets(tickets, { status: 'unknown' }), RangeError);
});
test('R-003 zero limit and empty input', () => {
  assert.deepEqual(listTickets(tickets, { limit: 0 }), []);
  assert.deepEqual(listTickets([]), []);
});
test('R-003 invalid limits are rejected', () => {
  for (const limit of [-1, 1.5, '1', null]) assert.throws(() => listTickets(tickets, { limit }), RangeError);
});
test('R-003 input order is preserved', () => {
  assert.deepEqual(ids(listTickets([...tickets].reverse(), { includeArchived: true })), ['T5', 'T4', 'T3', 'T2', 'T1']);
});
test('R-003 inputs are not mutated', () => {
  const snapshot = structuredClone(tickets);
  const options = Object.freeze({ status: 'open', limit: 1 });
  listTickets(tickets, options);
  assert.deepEqual(tickets, snapshot);
});
test('R-099 ticket creation remains unchanged', () => {
  assert.deepEqual(createTicket('T6', ' 新工单 '), { id: 'T6', title: '新工单', status: 'open', tags: [], archived: false });
  assert.throws(() => createTicket('T6', ' '), RangeError);
});
