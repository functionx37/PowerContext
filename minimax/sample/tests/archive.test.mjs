import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { listTickets } from '../src/tickets.mjs';
const tickets = JSON.parse(readFileSync(new URL('../data/tickets.json', import.meta.url)));
const ids = rows => rows.map(t => t.id);

test('R-001 default hides archived tickets', () => {
  assert.deepEqual(ids(listTickets(tickets)), ['T1', 'T3', 'T5']);
});
test('R-001 empty options hides archived tickets', () => {
  assert.deepEqual(ids(listTickets(tickets, {})), ['T1', 'T3', 'T5']);
});
test('R-001 false hides archived tickets', () => {
  assert.deepEqual(ids(listTickets(tickets, { includeArchived: false })), ['T1', 'T3', 'T5']);
});
test('R-001 only boolean true includes archived tickets', () => {
  for (const includeArchived of ['true', 1, null]) {
    assert.deepEqual(ids(listTickets(tickets, { includeArchived })), ['T1', 'T3', 'T5']);
  }
  assert.deepEqual(ids(listTickets(tickets, { includeArchived: true })), ['T1', 'T2', 'T3', 'T4', 'T5']);
});
test('R-002 status intersects archive filter', () => {
  assert.deepEqual(ids(listTickets(tickets, { status: 'open' })), ['T1']);
});
test('R-002 tag intersects archive filter', () => {
  assert.deepEqual(ids(listTickets(tickets, { tag: 'web' })), ['T3']);
});
test('R-003 filtering precedes limit', () => {
  assert.deepEqual(ids(listTickets(tickets, { limit: 2 })), ['T1', 'T3']);
});
test('R-001 legacy records without archived remain visible', () => {
  assert.deepEqual(ids(listTickets(tickets, { status: 'in_progress' })), ['T5']);
});
