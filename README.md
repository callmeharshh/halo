# Halo Journeys

**An AI travel agent for travellers with disabilities. Travel without guessing.**

Talk to a concierge of **fourteen specialist agents** about your trip and your needs, by typing or speaking ("3 days Pune to Goa, I use a wheelchair, budget 30000"). In about 20 seconds it returns an accessibility-first day-by-day plan. For every key place (airports, stations, hotels, sights) it researches accessibility on the web and shows each fact **with its source link**, never inventing ("unknown" stays "unknown"). Then it cross-checks an **on-chain community registry on Monad** where real travellers attest what they actually found accessible, so you can see what is *verified* versus only *claimed*.

Built at **Monad Blitz Pune V3**.

| | |
|---|---|
| **Live site** | https://callmeharshh.github.io/halo/ |
| **Concierge (chat)** | https://callmeharshh.github.io/halo/concierge.html (public site replays a real recorded session; run it locally to chat live) |
| **Classic planner** | https://callmeharshh.github.io/halo/journeys.html |
| **GitHub repo** | https://github.com/callmeharshh/halo |
| **AccessRegistry contract (Monad Testnet)** | [`0x3aaE87a424aA7F9fcD7FB98D27a621FcD6f14A7f`](https://testnet.monadscan.com/address/0x3aaE87a424aA7F9fcD7FB98D27a621FcD6f14A7f) · [verified on MonadVision](https://testnet.monadvision.com/address/0x3aaE87a424aA7F9fcD7FB98D27a621FcD6f14A7f) · [deploy tx](https://testnet.monadscan.com/tx/0x6d5df3f327aa5f142425e3743d3b3468fdaf13c0df9d3920c39898cfeedd7e5b) |
| **GuardVault contract (Halo Guard)** | [`0x3e89164abbc8852955F179D964B696a4b713418A`](https://testnet.monadscan.com/address/0x3e89164abbc8852955F179D964B696a4b713418A) · [verified](https://testnet.monadvision.com/address/0x3e89164abbc8852955F179D964B696a4b713418A) |
| **Network** | Monad Testnet, chain ID `10143` |
| **Demo video** | _added before submission_ |

## The problem
About 1.3 billion people live with a significant disability (WHO). For many, planning a trip means hours of searching, unclear mobility information, websites that say "accessible" with nothing to back it up, and the risk of arriving somewhere that is not. Many avoid travelling at all.

## What Halo Journeys does
1. **Plans** the trip around your needs (wheelchair, blind or low vision, deaf or hard of hearing, cognitive, elderly): few stops, rest breaks, no rushed transfers.
2. **Researches every key place** on the web and shows the facts with real source links. If sources do not say, it says "unknown". Confidence is *high* only when independent sources agree.
3. **Checks it against Monad.** The `AccessRegistry` contract holds attestations from real travellers: which of 10 features they actually found (step-free entrance, ramp, lift, accessible restroom, accessible room/seating, tactile paving/braille, hearing loop/sign language, quiet space, assistance, accessible parking), optionally marking "the venue confirmed this in writing". Each place gets an honest badge: **Venue-confirmed**, **Community-verified**, **1 traveller verified**, **Web-sourced only**, or **Unverified**.
4. **Helps you confirm.** It drafts the exact questions to send to the venue (email or WhatsApp). Been there? Attest what you found (the live on-chain transaction) and help the next traveller.
5. **Voice and accessibility.** Speak your request in the browser (English or Hindi) and have the plan read aloud. The page has a large-text toggle, a high-contrast toggle, keyboard and screen-reader support.

### Why on-chain
Accessibility claims are only useful if they are trustworthy. A public registry on Monad is tamper-evident, owned by no single company, and portable between apps. Each wallet has **one current attestation per place** (updating replaces it), so repeating cannot inflate the numbers.

## Run it yourself (macOS, about 5 minutes)
You need Python 3.11–3.13 and an [OpenAI API key](https://platform.openai.com/api-keys).

```bash
git clone https://github.com/callmeharshh/halo
cd halo
./setup.sh                 # creates .venv, installs everything, creates .env
# edit .env: set OPENAI_API_KEY
source .venv/bin/activate
python travel/server.py    # opens http://127.0.0.1:8780 : chat with the concierge live
```
To attest a place you need MetaMask on Monad Testnet with a little test MON ([faucet](https://faucet.monad.xyz)).

## The concierge: fourteen agents, one conversation
A root **concierge** hands each request to the right specialist (`transfer_to_agent`), and you can watch every hand-off in the chat.

| Tier | Agents |
|---|---|
| Core travel | `inspiration_agent`, `planning_agent`, `booking_agent` *(simulated)*, `pre_trip_agent`, `in_trip_agent`, `post_trip_agent` |
| Accessibility | `accessibility_research_agent`, `mobility_preparation_agent`, `transit_support_agent`, `barrier_navigation_agent` |
| Automation and safety | `notification_agent` *(simulated)*, `accessibility_communication_agent`, `web_checkin_agent` *(simulated)*, `smart_guardrails_agent` |

**Real:** itinerary planning, forced web research with source links, on-chain checks on Monad (the safety agent reads the registry), cost estimates (clearly labelled estimates, with disability-related expenses shown separately), checklists, risk review, barrier alternatives, message drafts, a personal profile that personalises every answer, and an on-chain attestation after the trip.
**Simulated, and labelled as such in the UI:** bookings, payments, web check-in, reminders, and sending messages (no airline, hotel, payment or email system is connected, and nothing is sent for you).

## Honest limitations
- Web sources can be wrong or out of date. That is exactly why traveller attestations and "confirm with the venue" exist. Always confirm before booking.
- The registry only becomes valuable with a community of attesters. Today it is a testnet demo with a handful of entries. Fake wallets are possible; the roadmap includes attester reputation and venue-signed confirmations.
- We have not yet tested with disabled travellers. The needs mapping is a starting point, not a substitute for their expertise.
- The public site shows a **sample plan** generated by the real agent; live planning runs locally because it needs an API key.

## Also built: Halo Guard (safe payments)
A second module, `GuardVault`: a family sets on-chain spending rules (per-payment and daily limits, trusted contacts only) that an AI helper device cannot exceed, with every approval recorded. The site has a "Try to move money" box that asks the real contract (a read-only dry run). The voice assistant for it runs with `python halo.py`. This is the same trust idea applied to a trip allowance.

## Project layout
| Path | Purpose |
|---|---|
| `travel/concierge.py` | The root concierge and the 14 specialist agents |
| `travel/agent.py` | Planning outline, forced web research with citations, drafts |
| `travel/server.py` | Local server: `/api/chat` and `/api/plan` (streaming), `/api/tts`, serves the pages |
| `docs/concierge.*` | The chat concierge (replays a real session on GitHub Pages, live mode locally) |
| `docs/journeys.*` | The classic form-based planner |
| `docs/index.html` | Public site with the live attestations feed |
| `contracts/AccessRegistry.sol` | Traveller attestation registry |
| `contracts/GuardVault.sol` | Family-owned spending rules (Halo Guard) |
| `halo.py`, `ui/`, `voice.py`, `agents.py`, `wallet.py` | Halo Guard voice assistant |
| `tests/`, `scripts/` | Regression checks (`python scripts/check_all.py`) and site helpers |

## Credits and honesty
- The idea of an AI agent for disabled travellers was **inspired by [Inclusive Travel Agent](https://github.com/codersbeyondborders/inclusive-travel-agent)** by Coders Beyond Borders, which won a prize at another hackathon, and the roster and structure of the concierge by Google's open-source [inclusive-travel-agent sample](https://github.com/google/adk-samples) (Apache-2.0). We copied no code. This repository is our own implementation, and our addition is the **traveller-verified on-chain registry** and source-linked research. We do not claim any of their research, user testing or integrations.
- We started from **[GemGuide](https://github.com/Sourajit1234/GemGuide)** by Sourajit (voice, eye-gaze and screen vision with Gemma 4), whose foundation we ported to macOS for Halo Guard.

Testnet only. Use a throwaway wallet. Not financial or medical advice.
