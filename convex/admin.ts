import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { mine, userArg, who } from "./users";

const TABLES = [
  "conversations", "lines", "people", "promises", "whispers", "chats", "tasks", "memories",
  "research", "settings",
] as const;

// One-time migration, and for tests: give every row that has no owner to this user.
// Returns how many rows were stamped in each table.
export const stamp = mutation({
  args: { userId: v.string() },
  handler: async (ctx, { userId }) => {
    const receipt: Record<string, number> = {};
    for (const table of TABLES) {
      const rows = (await ctx.db.query(table).collect()).filter((row) => row.userId === undefined);
      for (const row of rows) await ctx.db.patch(row._id, { userId });
      receipt[table] = rows.length;
    }
    return receipt;
  },
});

// How many rows this user has in each table, to check that users are kept apart.
export const counts = query({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    const user = who(userId);
    const out: Record<string, number> = {};
    for (const table of TABLES) {
      out[table] = (await ctx.db.query(table).collect()).filter((row) => mine(row, user)).length;
    }
    return out;
  },
});
