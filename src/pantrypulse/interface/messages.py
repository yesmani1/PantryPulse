"""All user-facing copy lives here.

INTERFACE owns message design, so the words are kept out of the handlers. When
IF-5 and IF-7 tune the expiry copy, they edit this file, not the plumbing.

Plain text for now — no parse_mode. The markup convention gets settled at IF-3,
when real item names (which need escaping) start being rendered.
"""

START = (
    "PantryPulse keeps food out of your bin.\n"
    "\n"
    "Send me a photo of a receipt or a package and I'll track what you bought "
    "and what it actually means when a date is printed on it. Best Before is "
    "about quality, not safety, and I treat it that way.\n"
    "\n"
    "Then I get out of your way. One message a day, only when something needs "
    "you. Nothing at risk means you hear nothing from me.\n"
    "\n"
    "Send a photo whenever you're ready — or send /demo to look around a "
    "sample pantry first, since yours starts empty."
)

# Shown when a handler raises. The traceback goes to the log, never to the user.
ERROR_GENERIC = (
    "Something went wrong on my end. Nothing was lost — try that again in a moment."
)

# Used only when the bot was started without its application services. The
# upload was received, but it cannot be analyzed or persisted in that mode.
PHOTO_RECEIVED = (
    "Photo received ({size_kb:.0f} KB).\n"
    "\n"
    "Photo analysis is not configured right now, so I have not read or saved "
    "anything from it. Please try again after the bot is fully started."
)

# Used when a handler is deliberately exercised without persistence services.
FEEDBACK_ACK = (
    "Noted: {name} — {response}.\n"
    "\n"
    "This isn't saved anywhere yet — that needs the feedback-recording "
    "agent, which isn't built. Once it exists, this exact tap is what "
    "feeds the rescue counter."
)

FEEDBACK_SAVED_ACK = "Saved: {name} — {response}. This updates your rescue history."

INGESTION_PREVIEW = (
    "I found {count} item{plural}:\n\n{items}\n\n"
    "Please confirm before I add {pronoun} to your pantry."
)
INGESTION_CONFIRMED = "Added {count} item{plural} to your pantry."
INGESTION_CANCELLED = "Okay — I did not add those items."

# Two models read every photo. Where they disagreed about a printed date,
# neither reading is trusted, because a single model states wrong dates just as
# confidently as right ones. Say that plainly rather than showing a guess.
INGESTION_UNVERIFIED = (
    "⚠ I couldn't read {count} date{plural} reliably — my two reads of the "
    "package disagreed, so I haven't used either. What's shown for {verb} a "
    "category estimate, not the printed date. Tap an item to set the real one."
)
INGESTION_STILL_UNVERIFIED = (
    "Just so it's clear: {names} would be saved with a category estimate, not "
    "the date printed on the package.\n\n"
    "You can set the real date first, or save anyway — it will stay marked as "
    "an estimate."
)
INGESTION_EXPIRED = "That photo preview has expired. Please send the photo again."
ASK_FOR_DATE = (
    "What date is printed on {name}?\n\n"
    "Send it as YYYY-MM-DD (for example 2027-04-16), or in a form like "
    "16/04/2027 or 16 Apr 2027."
)
DATE_NOT_UNDERSTOOD = (
    "I couldn't read that as a date. Try YYYY-MM-DD — for example 2027-04-16."
)

# IF-6 (the /help third of it). Lists what exists today and says plainly
# which parts are demo data -- a command list that oversells itself is worse
# than a short honest one.
HELP = (
    "Tap a button below, or type the matching command:\n"
    "\n"
    "Today / /today — your one daily check: what to use first, and what is "
    "merely past a quality date\n"
    "Pantry / /pantry — everything in your pantry\n"
    "Expiring / /expiring — items that need attention, with Used it / "
    "Still good / Tossed it buttons\n"
    "Recipe / /recipe — a rescue recipe for what's expiring, with Cook "
    "This / Another Recipe buttons\n"
    "Shopping / /shopping — a suggested shopping list you can approve, edit, or ignore\n"
    "Decision / /decision — one combined cook, shop, donate, or ignore plan\n"
    "Help / /help — this message\n"
    "/remove — strike out something I got wrong. It won't count as food "
    "wasted, because it was never food.\n"
    "/demo — fill this chat with a sample pantry, so there is something to "
    "look at before you have added anything. Send it again to switch back.\n"
    "\n"
    "Or just send a photo of a receipt or package.\n"
    "\n"
    "About dates, since they matter most here: two different models read "
    "every photo, and a printed date is kept only if both agree. Where they "
    "disagree you get a category estimate, clearly labelled as one, and a "
    "Set date button to put the real date in yourself. Every row tells you "
    "where its date came from — read from the package, estimated, or "
    "confirmed by you."
)

# Silence is a correct outcome, so this exists only for someone who asked.
NOTHING_TODAY = (
    "Nothing needs your attention today. I'll stay quiet unless something does."
)

# A brand-new chat is genuinely empty, so there is nothing to look at until
# someone photographs a receipt. This fills it with the sample household so the
# behaviour can be seen first and trusted second.
DEMO_ON = (
    "Demo pantry loaded — 30 sample items, not your groceries.\n"
    "\n"
    "Worth looking at:\n"
    "Today — the Greek yogurt is past its Best Before and I reassure you about "
    "it, while the sliced turkey is a Use By and I don't. Same message, "
    "opposite advice, because they are opposite kinds of date.\n"
    "Pantry — every row shows where its date came from; the baby spinach says "
    "outright that its date is a guess rather than a label I read.\n"
    "Expiring — the milk's Sell By has already passed and never appears at "
    "all: that date is for the shop's shelf rotation, not for you.\n"
    "\n"
    "Send /demo again to switch back to your own pantry. Sending a photo also "
    "switches back — at that point you have real groceries to talk about."
)
DEMO_OFF = (
    "Back to your own pantry. Send /demo any time to look at the sample one again."
)
DEMO_LEFT_BY_PHOTO = (
    "That's a real photo, so I've switched out of the demo pantry — what "
    "follows is your own."
)


# Undoing what the agent got wrong. A misread item used to be permanent: it
# showed in every listing and in the daily check, with no way to strike it out.
REMOVE_PROMPT = (
    "Which item shouldn't be here? Tap it and I'll strike it out.\n"
    "\n"
    "This is for things I got wrong — a misread label, or something I invented "
    "from a photo. It doesn't count as food wasted, because it was never food."
)
REMOVE_CONFIRMED = (
    "Struck out {name}. It won't appear in your pantry or the daily check "
    "again, and it hasn't been counted against your rescue figures."
)
REMOVE_NOTHING_TO_REMOVE = "There's nothing in your pantry to remove."
REMOVE_NOT_IN_DEMO = (
    "The sample pantry isn't yours to change — send /demo to switch back to "
    "your own first."
)
REMOVE_FAILED = "I couldn't remove that just now. Try again in a moment."


# Photo ingestion is the only thing here that costs money, and the bot has to
# stay open to judges through the judging window. Say what happened plainly:
# someone hitting a limit while evaluating in good faith deserves to know it is
# a spending guard and not a fault of theirs.
PHOTO_RATE_LIMITED_CHAT = (
    "That's a lot of photos in one go — I've paused reading them for a bit.\n"
    "\n"
    "Reading a photo is the one thing here that costs real money, so there's a "
    "cap per chat. Everything else still works: try Today, Pantry, or /demo. "
    "Photos will work again within the hour."
)
PHOTO_RATE_LIMITED_GLOBAL = (
    "I'm reading more photos than usual right now, so I've paused new ones "
    "briefly to stay inside the project's budget.\n"
    "\n"
    "Nothing is wrong with your photo. Everything else still works — try "
    "Today, Pantry, or /demo — and photos will be back shortly."
)
