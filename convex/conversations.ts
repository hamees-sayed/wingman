import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { mine, searchReach, takeMine, userArg, who } from "./users";

// Lines, promises and whispers have no life of their own: they belong to whoever owns their
// conversation, so the functions below check the conversation and then read by its id.

export const start = mutation({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    return await ctx.db.insert("conversations", { startedAt: Date.now(), peopleIds: [], userId: who(userId) });
  },
});

export const end = mutation({
  args: {
    id: v.id("conversations"),
    title: v.optional(v.string()),
    summary: v.optional(v.string()),
    points: v.optional(v.array(v.string())),
    ...userArg,
  },
  handler: async (ctx, { id, title, summary, points, userId }) => {
    const conversation = await ctx.db.get(id);
    if (!conversation || !mine(conversation, who(userId))) return;
    await ctx.db.patch(id, { endedAt: conversation.endedAt ?? Date.now(), title, summary, points });
  },
});

// The same people carried on after a pause: the conversation is not over after all.
export const reopen = mutation({
  args: { id: v.id("conversations"), ...userArg },
  handler: async (ctx, { id, userId }) => {
    const conversation = await ctx.db.get(id);
    if (conversation && mine(conversation, who(userId))) await ctx.db.patch(id, { endedAt: undefined });
  },
});

export const addPerson = mutation({
  args: { id: v.id("conversations"), personId: v.id("people"), ...userArg },
  handler: async (ctx, { id, personId, userId }) => {
    const user = who(userId);
    const conversation = await ctx.db.get(id);
    if (!conversation || !mine(conversation, user) || conversation.peopleIds.includes(personId)) return;
    // Another user's person cannot be put in this one's conversation.
    if (!mine(await ctx.db.get(personId), user)) return;
    await ctx.db.patch(id, { peopleIds: [...conversation.peopleIds, personId] });
  },
});

export const addLine = mutation({
  args: {
    conversationId: v.id("conversations"),
    who: v.union(v.literal("you"), v.literal("other"), v.literal("unknown")),
    personId: v.optional(v.id("people")),
    label: v.string(),
    text: v.string(),
    start: v.number(),
    end: v.number(),
    ...userArg,
  },
  handler: async (ctx, { userId, ...line }) => {
    const user = who(userId);
    if (!mine(await ctx.db.get(line.conversationId), user)) return null;
    return await ctx.db.insert("lines", { ...line, userId: user, at: Date.now() });
  },
});

// A speaker was named after some of their lines were saved as "Speaker 2".
export const relabel = mutation({
  args: {
    conversationId: v.id("conversations"),
    fromLabel: v.string(),
    label: v.string(),
    who: v.union(v.literal("you"), v.literal("other"), v.literal("unknown")),
    personId: v.optional(v.id("people")),
    ...userArg,
  },
  handler: async (ctx, { conversationId, fromLabel, label, who: speaker, personId, userId }) => {
    if (!mine(await ctx.db.get(conversationId), who(userId))) return;
    const lines = await ctx.db
      .query("lines")
      .withIndex("by_conversation", (q) => q.eq("conversationId", conversationId))
      .collect();
    for (const line of lines) {
      if (line.label === fromLabel) await ctx.db.patch(line._id, { label, who: speaker, personId });
    }
  },
});

export const retract = mutation({
  args: { lineIds: v.array(v.id("lines")), ...userArg },
  handler: async (ctx, { lineIds, userId }) => {
    const user = who(userId);
    for (const id of lineIds) {
      const line = await ctx.db.get(id);
      if (line && mine(line, user)) await ctx.db.patch(id, { retracted: true });
    }
  },
});

export const lines = query({
  args: { conversationId: v.id("conversations"), ...userArg },
  handler: async (ctx, { conversationId, userId }) => {
    if (!mine(await ctx.db.get(conversationId), who(userId))) return [];
    return await ctx.db
      .query("lines")
      .withIndex("by_conversation", (q) => q.eq("conversationId", conversationId))
      .collect();
  },
});

export const list = query({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    return await takeMine(ctx.db.query("conversations").withIndex("by_started").order("desc"), who(userId), 50);
  },
});

// The Recaps screen: finished conversations worth reading, each with who was there and what
// came out of it. Scraps of a few words with nothing in them are left out.
export const feed = query({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    const user = who(userId);
    const recent = await takeMine(ctx.db.query("conversations").withIndex("by_started").order("desc"), user, 40);
    const tasks = (await ctx.db.query("tasks").collect()).filter((task) => mine(task, user));
    const out = [];
    for (const conversation of recent) {
      if (conversation.endedAt === undefined) continue;
      const lines = await ctx.db
        .query("lines")
        .withIndex("by_conversation", (q) => q.eq("conversationId", conversation._id))
        .collect();
      const promises = await ctx.db
        .query("promises")
        .withIndex("by_conversation", (q) => q.eq("conversationId", conversation._id))
        .collect();
      const whispers = await ctx.db
        .query("whispers")
        .withIndex("by_conversation", (q) => q.eq("conversationId", conversation._id))
        .collect();
      const todos = tasks.filter((task) => task.conversationId === conversation._id).length;
      const words = lines.reduce((sum, line) => sum + line.text.split(" ").length, 0);
      if (words < 25 && promises.length === 0 && todos === 0) continue;
      // Something playing nearby (a video, other people's talk) is not a conversation of yours.
      const yours = lines.filter((line) => line.who === "you").reduce((sum, line) => sum + line.text.split(" ").length, 0);
      if (yours < 5 && todos === 0) continue;
      const people = [];
      for (const id of conversation.peopleIds) {
        const person = await ctx.db.get(id);
        if (person && mine(person, user) && !person.isOwner) people.push(person.name);
      }
      out.push({
        _id: conversation._id,
        title: conversation.title ?? "Conversation",
        summary: conversation.summary ?? "",
        startedAt: conversation.startedAt,
        minutes: Math.max(1, Math.round((conversation.endedAt - conversation.startedAt) / 60000)),
        people,
        promises: promises.length,
        todos,
        whispers: whispers.filter(
          // Unprompted help only: answers to "Wingman, ..." and check-ins are not whispers.
          (w) => (w.outcome === "spoken" || w.outcome === "cut") && w.kind !== "ask" && w.kind !== "checkin",
        ).length,
      });
    }
    return out;
  },
});

// Everything the agent needs to answer about recent days: each conversation with its lines.
export const digest = query({
  args: { limit: v.optional(v.number()), ...userArg },
  handler: async (ctx, { limit, userId }) => {
    const recent = await takeMine(
      ctx.db.query("conversations").withIndex("by_started").order("desc"),
      who(userId),
      Math.min(limit ?? 6, 12),
    );
    const out = [];
    for (const conversation of recent) {
      const lines = await ctx.db
        .query("lines")
        .withIndex("by_conversation", (q) => q.eq("conversationId", conversation._id))
        .take(120);
      out.push({
        _id: conversation._id,
        title: conversation.title ?? (conversation.endedAt ? "Conversation" : "Happening now"),
        summary: conversation.summary ?? "",
        startedAt: conversation.startedAt,
        live: conversation.endedAt === undefined,
        lines: lines
          .filter((line) => !line.retracted)
          .map((line) => ({ label: line.label, text: line.text })),
      });
    }
    return out;
  },
});

// The Home screen in one read: what is happening now, what must not be dropped, and what
// Wingman caught today.
export const home = query({
  args: { since: v.number(), ...userArg },
  handler: async (ctx, { since, userId }) => {
    const user = who(userId);
    const [latest] = await takeMine(ctx.db.query("conversations").withIndex("by_started").order("desc"), user, 1);
    const live = latest && latest.endedAt === undefined ? latest : null;
    const open = await takeMine(
      ctx.db
        .query("promises")
        .withIndex("by_status", (q) => q.eq("status", "open"))
        .order("desc"),
      user,
      100,
    );

    let now = null;
    if (live) {
      const people = [];
      for (const id of live.peopleIds) {
        const person = await ctx.db.get(id);
        if (person && mine(person, user)) people.push({ _id: person._id, name: person.name });
      }
      const lines = await ctx.db
        .query("lines")
        .withIndex("by_conversation", (q) => q.eq("conversationId", live._id))
        .collect();
      const names = new Set(people.map((p) => p.name.toLowerCase()));
      now = {
        _id: live._id,
        startedAt: live.startedAt,
        people,
        lines: lines.length,
        lastLine: lines.length ? lines[lines.length - 1].text : "",
        // Open promises with the people in this conversation, made before it began.
        between: open.filter(
          (p) => p.conversationId !== live._id && names.has(p.person.toLowerCase()),
        ),
      };
    }

    const today = await takeMine(
      ctx.db
        .query("conversations")
        .withIndex("by_started", (q) => q.gte("startedAt", since))
        .order("desc"),
      user,
      30,
    );
    const caught = [];
    for (const conversation of today) {
      const title = conversation.title ?? "Now";
      const whispers = await ctx.db
        .query("whispers")
        .withIndex("by_conversation", (q) => q.eq("conversationId", conversation._id))
        .collect();
      for (const w of whispers) {
        if (w.outcome === "spoken" || w.outcome === "cut")
          caught.push({ kind: "whisper", text: w.text, detail: w.kind, at: w.at, title });
      }
      const promises = await ctx.db
        .query("promises")
        .withIndex("by_conversation", (q) => q.eq("conversationId", conversation._id))
        .collect();
      for (const p of promises)
        caught.push({
          kind: p.by === "you" ? "promise" : "owed",
          text: p.by === "you" ? `You owe ${p.person} ${p.what}` : `${p.person} owes you ${p.what}`,
          detail: p.due ?? "",
          at: p.createdAt,
          title,
        });
    }
    caught.sort((a, b) => b.at - a.at);

    const tasks = (
      await ctx.db
        .query("tasks")
        .withIndex("by_status", (q) => q.eq("status", "open"))
        .collect()
    )
      .filter((task) => mine(task, user))
      .sort((a, b) => (a.due ?? Infinity) - (b.due ?? Infinity) || b.createdAt - a.createdAt);

    const research = await takeMine(ctx.db.query("research").withIndex("by_created").order("desc"), user, 6);
    const suggested = await takeMine(
      ctx.db
        .query("tasks")
        .withIndex("by_status", (q) => q.eq("status", "suggested"))
        .order("desc"),
      user,
      10,
    );

    // People heard in the last few conversations, most recent first.
    const met = [];
    const seen = new Set<string>();
    const lately = await takeMine(ctx.db.query("conversations").withIndex("by_started").order("desc"), user, 25);
    for (const conversation of lately) {
      for (const id of conversation.peopleIds) {
        if (seen.has(id) || met.length >= 5) continue;
        seen.add(id);
        const person = await ctx.db.get(id);
        if (!person || !mine(person, user) || person.isOwner) continue;
        met.push({
          _id: person._id,
          name: person.name,
          about: person.about ?? "",
          at: conversation.startedAt,
          where: conversation.title ?? "",
        });
      }
    }

    return {
      now,
      met,
      research: research.map(({ report, ...rest }) => rest),
      suggested,
      tasks: tasks.slice(0, 20),
      owe: open.filter((p) => p.by === "you").slice(0, 20),
      owed: open.filter((p) => p.by === "them").slice(0, 20),
      caught: caught.slice(0, 20),
      earlier: today
        .filter((c) => c.endedAt !== undefined)
        .map((c) => ({ _id: c._id, title: c.title ?? "Conversation", startedAt: c.startedAt })),
    };
  },
});

export const latest = query({
  args: { ...userArg },
  handler: async (ctx, { userId }) => {
    const [conversation] = await takeMine(ctx.db.query("conversations").withIndex("by_started").order("desc"), who(userId), 1);
    return conversation ?? null;
  },
});

// The Recap screen: one conversation with everything caught in it.
export const recap = query({
  args: { id: v.id("conversations"), ...userArg },
  handler: async (ctx, { id, userId }) => {
    const user = who(userId);
    const conversation = await ctx.db.get(id);
    if (!conversation || !mine(conversation, user)) return null;
    const people = [];
    for (const personId of conversation.peopleIds) {
      const person = await ctx.db.get(personId);
      if (person && mine(person, user)) people.push({ _id: person._id, name: person.name, about: person.about });
    }
    const promises = await ctx.db
      .query("promises")
      .withIndex("by_conversation", (q) => q.eq("conversationId", id))
      .collect();
    const whispers = await ctx.db
      .query("whispers")
      .withIndex("by_conversation", (q) => q.eq("conversationId", id))
      .collect();
    const todos = (await ctx.db.query("tasks").collect()).filter(
      (task) => task.conversationId === id && mine(task, user),
    );
    return { conversation, people, promises, whispers, todos };
  },
});

// Words from earlier conversations, for "the number I mentioned last week".
// Retracted lines are found, so Wingman knows something was taken back, but never shown.
export const search = query({
  args: {
    text: v.string(),
    who: v.optional(v.union(v.literal("you"), v.literal("other"), v.literal("unknown"))),
    exceptConversation: v.optional(v.id("conversations")),
    limit: v.optional(v.number()),
    ...userArg,
  },
  handler: async (ctx, { text, who: speaker, exceptConversation, limit, userId }) => {
    const user = who(userId);
    const found = await ctx.db
      .query("lines")
      .withSearchIndex("search_text", (q) => {
        const search = q.search("text", text);
        return speaker ? search.eq("who", speaker) : search;
      })
      .take(searchReach(Math.min(limit ?? 8, 24)));
    return found
      .filter((line) => mine(line, user) && line.conversationId !== exceptConversation)
      .slice(0, limit ?? 8)
      .map((line) => ({
        _id: line._id,
        conversationId: line.conversationId,
        label: line.label,
        who: line.who,
        at: line.at,
        text: line.retracted ? "[You later asked Wingman to forget what was said here.]" : line.text,
        retracted: line.retracted ?? false,
      }));
  },
});

// Delete a conversation and everything derived from it; returns what was removed.
export const remove = mutation({
  args: { id: v.id("conversations"), ...userArg },
  handler: async (ctx, { id, userId }) => {
    const receipt = { lines: 0, promises: 0, whispers: 0 };
    if (!mine(await ctx.db.get(id), who(userId))) return receipt;
    const lines = await ctx.db
      .query("lines")
      .withIndex("by_conversation", (q) => q.eq("conversationId", id))
      .collect();
    for (const line of lines) await ctx.db.delete(line._id);
    receipt.lines = lines.length;
    const promises = await ctx.db
      .query("promises")
      .withIndex("by_conversation", (q) => q.eq("conversationId", id))
      .collect();
    for (const promise of promises) await ctx.db.delete(promise._id);
    receipt.promises = promises.length;
    const whispers = await ctx.db
      .query("whispers")
      .withIndex("by_conversation", (q) => q.eq("conversationId", id))
      .collect();
    for (const whisper of whispers) await ctx.db.delete(whisper._id);
    receipt.whispers = whispers.length;
    if (await ctx.db.get(id)) await ctx.db.delete(id);
    return receipt;
  },
});
