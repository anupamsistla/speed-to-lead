# Loom walkthrough: 2 to 3 minutes

Written for the person recording (you), to show a prospect with 50+ employees, a sales team and a
CRM. Target length 2:45. Say it in your own words. The right-hand column is what to do on screen.

## Before you hit record (5 minutes)

- [ ] **Make it about them.** Find one real observation about the prospect: fill in their web form
      or text their number and note how long they took to answer. Write it down. It is your hook.
- [ ] `make eval` and read the fresh numbers (a full run takes about two minutes). Do not quote
      numbers you have not just seen. If it prints `EVAL INVALID`, fix the API problem first.
- [ ] Start clean: `cd web && npm run build`, then `python run.py --company sunrise_solar` and open
      `http://localhost:8000`. This hides the dev header. Add `?dev=1` to bring it back.
- [ ] Pick the company that matches the prospect (`?dev=1` and the company switcher), set the clock
      to **Business hours**, browser at 1440px wide, notifications off.
- [ ] Rehearse once with **Play** on a saved scenario so you know how a good run looks.
- [ ] Backup plan: if the model is slow, use **Replay a saved scenario**. It runs the same flow.

## The walkthrough

| Time | On screen | What to say |
|---|---|---|
| **0:00 to 0:15** Observation hook | Your note (or a screenshot of their form). Then the app | "I filled out your contact form at 2:14 on Tuesday and the first reply came at 4:50. Most buyers talk to whoever answers first, so I built something that answers in seconds. This is a demo on a fictional company, so nobody real is involved." Use your real observation. |
| **0:15 to 0:30** Live lead | Type into **Lead simulator**: a name, a phone, and a realistic message with answers in it. Press **Send lead**. Point at the **First response** timer | "A lead comes in from a web form, a missed call or a text. The clock starts now." |
| **0:30 to 1:00** The reply | Chat thread fills in. Timer stops (a few seconds). Open **Agent trace** | "It replied in about [read the timer]. It already checked the CRM for this person, asked only what it still needed, scored them, and routed them by zip. This is every step, live: the tool, the arguments, how long each took." |
| **1:00 to 1:20** Booking | Reply as the lead with **The first one works**. Show **Appointment** card | "It offers real openings from the rep's calendar, and when the lead picks one it books it. Hot leads get the earliest times." |
| **1:20 to 1:35** CRM record | **CRM record** card, then **Qualification answers** and **Lead score** breakdown | "Everything lands in the CRM with the stage moved, using your field names, plus a summary. The score is not a black box: each rule that fired is listed with its points." |
| **1:35 to 1:45** Slack ping | **Slack notifications** card | "The assigned rep gets pinged immediately, with the score, the answers and the appointment. A person can take over any time with this button." (Press **Take over** only if you want to show it.) |
| **1:45 to 2:00** Eval metrics | Terminal: the table and metrics from `make eval` | "I don't ask you to trust it. I test it on [N] synthetic leads, including angry customers, spam, prompt injection and people asking for discounts. First response median [x] seconds, [y]% of scenarios passed, [z] guardrail violations. It never quotes a price you have not approved." Read the numbers you just saw. |
| **2:00 to 3:00** Architecture close | Slide or this README's diagram | See below. |

## 60-second architecture close

Say these five things, one per ~12 seconds:

1. **Engine plus config.** "The engine never mentions your company. Everything specific to you is a folder of
   config: your tone, your questions, how you score, which office gets which zip, your CRM fields,
   and the facts it is allowed to state."
2. **Fast to set up.** "To onboard you, I draft that folder from your website. Every guess is marked,
   every fact is verified against your own pages, and it will not run until a human has reviewed it."
3. **Plugs into what you have.** "Your CRM, your calendar, your Slack and your SMS number sit behind
   adapters. Today the demo is mocked. HubSpot and Slack are built. SMS and Google Calendar are next."
4. **Safe by construction.** "The rules are enforced in code, not just asked nicely in a prompt: no
   prices or guarantees unless they are in your knowledge base, quiet hours, instant opt-out, and
   it treats whatever a lead types as untrusted. It hands off to a person when someone is angry,
   asks for one, or asks twice something it cannot answer."
5. **The ask.** "Let's connect it to a copy of your form and run your last 20 real leads through
   it, and you can judge the replies yourself."

## If something goes wrong on camera

| Problem | Fix |
|---|---|
| Reply is slow | Say so, point at the trace: "that is the model thinking". Or press **Play** on a saved scenario next time |
| Reply is held, timer says Queued | The clock is in quiet hours. That is a feature to show: "it will not text a lead at 10pm". Then switch the clock to Business hours |
| "Can't reach the API" | The API is not running. Start `python run.py --company <slug>` |
| `ANTHROPIC_API_KEY is not set` or a billing error | Fix `.env` or your Anthropic credits before recording. Check with `make eval EVAL_ARGS="--only stop_message"` |

## Do not say

- Do not claim a number you have not just measured. Read it off the screen.
- The HubSpot and Slack adapters are built and unit tested against fakes. Say "built" and "connected in
  your trial", not "running in production".
- Do not call the leads real. Everything here is synthetic.
