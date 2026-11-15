import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { mine, takeMine, userArg, who } from "./users";

const outcome = v.union(
  v.literal("spoken"),
  v.literal("card"),
  v.literal("held"),
  v.literal("declined"),
  v.literal("stale"),
  v.literal("cut"),
);

export const log = mutation({
  args: {
    conversationId: v.id("conversations"),
    kind: v.string(),
    text: v.string(),
    why: v.string(),
    outcome,
    confidence: v.number(),
    source: v.optional(v.string()),
    conversationSeconds: v.number(),
    latencyMs: v.optional(v.number()),
    ...userArg,
  },
  handler: async (ctx, { userId, ...whisper }) => {
    // A whisper belongs to whoever owns its conversation; someone else's is not there to log to.
    const user = who(userId);
    if (!mine(await ctx.db.get(whisper.conversationId), user)) return null;
    return await ctx.db.insert("whispers", { ...whisper, userId: user, at: Date.now() });
  },
});

export const setOutcome = mutation({
  args: { id: v.id("whispers"), outcome, ...userArg },
  handler: async (ctx, { id, outcome, userId }) => {
    const whisper = await ctx.db.get(id);
    if (!whisper || !mine(whisper, who(userId))) return;
    await ctx.db.patch(id, { outcome });
  },
});

export const grade = mutation({
  args: {
    id: v.id("whispers"),
    grade: v.optional(v.union(v.literal("up"), v.literal("down"))),
    ...userArg,
  },
  handler: async (ctx, { id, grade, userId }) => {
    const whisper = await ctx.db.get(id);
    if (!whisper || !mine(whisper, who(userId))) return;
    await ctx.db.patch(id, { grade });
  },
});

export const forConversation = query({
  args: { conversationId: v.id("conversations"), ...userArg },
  handler: async (ctx, { conversationId, userId }) => {
    if (!mine(await ctx.db.get(conversationId), who(userId))) return [];
    return await ctx.db
      .query("whispers")
      .withIndex("by_conversation", (q) => q.eq("conversationId", conversationId))
      .collect();
  },
});

// Thumbs per kind, so the bar for each kind of whisper can move on its own.
export const grades = query({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    const graded = (await takeMine(ctx.db.query("whispers").order("desc"), who(userId), 500)).filter(
      (whisper) => whisper.grade !== undefined,
    );
    const byKind: Record<string, { up: number; down: number }> = {};
    for (const whisper of graded) {
      const tally = (byKind[whisper.kind] ??= { up: 0, down: 0 });
      tally[whisper.grade!] += 1;
    }
    return byKind;
  },
});
