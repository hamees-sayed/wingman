import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

// Wingman's memory. Text only: audio is never stored.
export default defineSchema({
  // One stretch of listening, from Listen to Pause (or five quiet minutes).
  conversations: defineTable({
    startedAt: v.number(),
    endedAt: v.optional(v.number()),
    title: v.optional(v.string()),
    summary: v.optional(v.string()),
    points: v.optional(v.array(v.string())), // the few things worth keeping from it
    peopleIds: v.array(v.id("people")),
  }).index("by_started", ["startedAt"]),

  // What one speaker said in a row. `who` is "you", "other" or "unknown";
  // personId names the other speaker once known.
  lines: defineTable({
    conversationId: v.id("conversations"),
    who: v.union(v.literal("you"), v.literal("other"), v.literal("unknown")),
    personId: v.optional(v.id("people")),
    label: v.string(), // what the screen shows: "You", "Priya", "Speaker 2"
    text: v.string(),
    start: v.number(), // seconds into the conversation
    end: v.number(),
    at: v.number(), // wall clock, ms
    retracted: v.optional(v.boolean()), // "forget what I just said"
  })
    .index("by_conversation", ["conversationId", "start"])
    .searchIndex("search_text", { searchField: "text", filterFields: ["who"] }),

  // People heard named. The owner is the one row with isOwner.
  people: defineTable({
    name: v.string(),
    isOwner: v.boolean(),
    about: v.optional(v.string()), // "design lead at Acme"
    voiceprint: v.optional(v.array(v.float64())),
    voiceSeconds: v.optional(v.number()), // how much speech the voiceprint rests on
    firstMet: v.number(),
    lastMet: v.number(),
  })
    .index("by_owner", ["isOwner"])
    .searchIndex("search_name", { searchField: "name" }),

  promises: defineTable({
    conversationId: v.id("conversations"),
    by: v.union(v.literal("you"), v.literal("them")),
    personId: v.optional(v.id("people")),
    person: v.string(), // who it was made to, or by
    what: v.string(),
    due: v.optional(v.string()), // as said, plus an ISO date when one could be worked out
    dueDate: v.optional(v.string()),
    status: v.union(v.literal("open"), v.literal("done"), v.literal("dropped")),
    lineId: v.optional(v.id("lines")),
    createdAt: v.number(),
  })
    .index("by_status", ["status", "createdAt"])
    .index("by_conversation", ["conversationId"]),

  // Every moment the gate considered, spoken or not, for grading.
  whispers: defineTable({
    conversationId: v.id("conversations"),
    kind: v.string(), // name | fact | promise | ask | brief | clash
    text: v.string(), // what was, or would have been, said
    why: v.string(),
    outcome: v.union(
      v.literal("spoken"),
      v.literal("card"), // shown, not spoken
      v.literal("held"), // rules said no
      v.literal("declined"), // nothing reliable to say
      v.literal("stale"), // the moment passed
      v.literal("cut"), // you spoke over it
    ),
    confidence: v.number(),
    source: v.optional(v.string()), // where the answer came from
    at: v.number(),
    conversationSeconds: v.number(),
    latencyMs: v.optional(v.number()), // stall to first audio
    grade: v.optional(v.union(v.literal("up"), v.literal("down"))),
  }).index("by_conversation", ["conversationId", "at"]),

  // The owner's own chats with Wingman: questions, plans, and its answers.
  chats: defineTable({
    role: v.union(v.literal("you"), v.literal("wingman")),
    text: v.string(),
    sources: v.optional(v.array(v.string())), // conversation titles an answer drew on
    at: v.number(),
  }).index("by_at", ["at"]),

  // Things the owner asked Wingman to do: notes to keep and reminders to bring back.
  tasks: defineTable({
    kind: v.union(v.literal("reminder"), v.literal("note")),
    text: v.string(),
    due: v.optional(v.number()), // ms, for reminders with a time
    dueText: v.optional(v.string()), // as the owner said it: "8 am today"
    // "suggested": Wingman proposed it after a conversation and is waiting for a yes or no.
    status: v.union(v.literal("open"), v.literal("done"), v.literal("suggested")),
    fired: v.optional(v.boolean()), // the reminder has been spoken
    auto: v.optional(v.boolean()), // Wingman added it by itself after a conversation
    doneAt: v.optional(v.number()), // when it was marked done
    doneHow: v.optional(v.string()), // "tapped" on the screen, or "said" to Wingman
    conversationId: v.optional(v.id("conversations")),
    createdAt: v.number(),
  }).index("by_status", ["status", "createdAt"]),

  // Facts about the owner brought in from elsewhere, such as another assistant's memory.
  memories: defineTable({
    text: v.string(),
    source: v.string(), // "ChatGPT", "Claude", "Typed"
    createdAt: v.number(),
  }).searchIndex("search_text", { searchField: "text" }),

  // Research the owner asked for: done in the background, announced when ready.
  research: defineTable({
    topic: v.string(),
    status: v.union(v.literal("working"), v.literal("ready"), v.literal("failed")),
    short: v.optional(v.string()), // two or three sentences, for saying aloud
    report: v.optional(v.string()),
    sources: v.optional(v.array(v.string())),
    announced: v.optional(v.boolean()),
    createdAt: v.number(),
    readyAt: v.optional(v.number()),
  }).index("by_created", ["createdAt"]),

  // One row: the owner's controls.
  settings: defineTable({
    eagerness: v.union(v.literal("quiet"), v.literal("normal")),
    demo: v.boolean(),
    listening: v.boolean(),
    state: v.optional(v.string()), // what the Live screen shows: listening, paused, whispering
    checkins: v.optional(v.boolean()), // may Wingman ask the owner a question in a quiet moment
    profile: v.optional(v.string()), // the written-up picture of the owner, as JSON
  }),
});
