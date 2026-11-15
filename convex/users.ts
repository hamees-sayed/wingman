import { v } from "convex/values";

// Who a row belongs to. Wingman began with one person, so rows saved before there were
// users carry no userId: those are the legacy owner's, whose id is "owner".

// Spread into every function's args. Left out, the caller is the legacy owner.
export const userArg = { userId: v.optional(v.string()) };

export function who(userId?: string): string {
  return userId ?? "owner";
}

// Note that a missing row counts as the legacy owner's, so "does it exist" is a separate check.
export function mine(row: { userId?: string } | null, user: string): boolean {
  return (row?.userId ?? "owner") === user;
}

// The first `limit` of a query's rows that are this user's, in the query's own order.
// Reading on until enough are found (not take(n) and then filtering) means another user's
// rows can never crowd these out; with one user it reads exactly what take(n) did.
export async function takeMine<Row extends { userId?: string }>(
  rows: AsyncIterable<Row>,
  user: string,
  limit: number,
): Promise<Row[]> {
  const out: Row[] = [];
  if (limit <= 0) return out;
  for await (const row of rows) {
    if (!mine(row, user)) continue;
    out.push(row);
    if (out.length >= limit) break;
  }
  return out;
}

// How many search results to read so that enough are left once other users' are dropped.
// Search cannot filter on "no userId", which is what the legacy owner's rows have.
export function searchReach(limit: number): number {
  return Math.max(limit, Math.min(limit * 4, 100));
}
