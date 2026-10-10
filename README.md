# Halo

**A team of personal AI agents for the people the AI age is leaving behind, with money rules enforced on-chain by a family-owned smart contract.**

Halo is a voice and eye-gaze controlled assistant for people who are not tech-savvy or cannot use a keyboard and mouse: the elderly, people with physical disabilities, a society watchman who lives on WhatsApp and UPI. A team of AI agents runs the computer in English, Hindi or Hinglish, and a **smart contract on Monad, not the AI, has the final say on every payment.** A family member owns the vault and sets the rules; the person's device can only spend inside them.

Built at **Monad Blitz Pune V3**.

| | |
|---|---|
| **Live site** | https://callmeharshh.github.io/halo/ (live on-chain feed of real payments) |
| **GitHub repo** | https://github.com/callmeharshh/halo |
| **Contract (Monad Testnet)** | [`0x3e89164abbc8852955F179D964B696a4b713418A`](https://testnet.monadscan.com/address/0x3e89164abbc8852955F179D964B696a4b713418A) |
| **Verified source** | [MonadVision (Sourcify)](https://testnet.monadvision.com/address/0x3e89164abbc8852955F179D964B696a4b713418A) · [Monadscan](https://testnet.monadscan.com/address/0x3e89164abbc8852955F179D964B696a4b713418A) |
| **Deploy tx** | [`0x43356d3c…1921b`](https://testnet.monadscan.com/tx/0x43356d3c4b6240ea3fada7a69ff3e6d68e455ed6a557fd40effa65bfd941921b) |
| **Family Console** | https://callmeharshh.github.io/halo/console.html · [read-only demo vault](https://callmeharshh.github.io/halo/console.html?owner=0xb5848eF465b06Ade36461e0f49aE2809Bae08b98) (no wallet needed) |
| **Network** | Monad Testnet, chain ID `10143` |
| **Demo video** | _added before submission_ |

## The problem

About 1.3 billion people live with a significant disability (WHO). For many of them, voice and eye gaze are the main way to use a computer, and AI agents that can control a computer are a huge accessibility win. But an agent that can also **move money** is risky when the user cannot quickly grab the controls if it hallucinates or is hijacked. App-level checks can be bypassed. A contract's rules cannot.

## What Halo does

Say *"Open Safari"*, *"What's on my screen?"*, *"Dictate an email"*, or look at a button and blink to click. Say *"Send 0.1 MON to Alice"* and:

1. The **Orchestrator** routes the request to the **Wallet agent**.
2. The **Guardian** reviews it and asks out loud: *"Send 0.1 MON to Alice, address ending 9b39. Say confirm or cancel."*
3. You approve by **voice ("confirm")**, **double-blink**, or a **button**. Closing your eyes for 1.6s, or saying "cancel", stops it. Silence also cancels.
4. The Wallet agent calls **`GuardVault.guardedSend`**. The contract enforces your limits and **permanently records how the payment was approved** (`voice`, `double-blink`, `button`).

### Safety: speech recognition will mishear, so we make mistakes small

We do **not** claim voice payments are flawless. Instead every step is bounded, visible and defaults to *not sending*:

- The amount the AI wants to send must **appear in what the user literally said** (tested: "1" is never accepted for "zero point one"; "bhej do" is not read as the number two).
- Names are matched phonetically ("Alis" → Alice) but an ambiguous match is refused and the user is asked again.
- The Guardian reads the payment back digit by digit, and only starts listening for "confirm" **after the read-back finishes**, so it never hears itself or stray chatter. Silence cancels. Cancel always beats confirm. Confirmation works in English and Hindi ("haan", "nahi").
- One pending payment at a time, plus a cooldown after each send.
- Finally the contract enforces limits no matter what the AI or the speech recogniser did.

Checks: `python scripts/check_all.py` runs the whole regression suite (safety unit tests, on-chain/contract consistency, the public site, agent behaviour plus a Scam Shield test set, the server protocol, the browser UI end to end, and the Family Console with a wallet). `python scripts/check_all.py --live-tx` also sends one real payment.

### Family-owned vault (the elderly / disabled user's safety net)

In **family mode** a family member's wallet owns the vault (`VAULT_OWNER` in `.env`). They use the **[Family Console](https://callmeharshh.github.io/halo/console.html)** (connect a wallet) to deposit funds, set per-payment and daily limits, switch on *trusted contacts only*, manage the contact book, approve the assistant's device, and **pause or revoke** it. The person's device holds only an *agent key*: it spends inside those rules and cannot change them. Tested on-chain: a device that tries to raise its own limits only edits its own empty policy and still cannot touch the family's vault.

### Scam Shield

Ask *"Is this message safe?"* (or in Hinglish) and the Vision agent reads the screen and flags OTP/PIN requests, fake KYC deadlines and "pay now" pressure, with a plain-language instruction. Try it with [`demo/scam_message.html`](demo/scam_message.html) (a fictional "Sunrise Bank" message).

### Agents

```
Voice / Gaze ─► Orchestrator ─┬─► System agent   open apps/files/web, keys, scroll, volume, timers, clipboard
                              ├─► Vision agent   looks at the screen and describes/reads it
                              ├─► Writer agent   dictation → cleaned text (grammar, code, LaTeX) typed into any app
                              └─► Wallet agent ─► Guardian (human confirm) ─► GuardVault.sol (on Monad)
```

### GuardVault (smart contract)

[`contracts/GuardVault.sol`](contracts/GuardVault.sol) gives every user a vault and an on-chain spending policy:

- **Per-transaction limit** and **daily limit**: anything above reverts.
- **Trusted-contacts-only mode** and an **enumerable on-chain contact book**: *"Alice"* resolves on-chain; the device can read it but not edit it.
- **Owner vs agent**: the owner (family) sets policy, contacts and the approved agent key; the agent can only call `guardedSend`.
- **Pause / revoke**: the owner can stop the agent instantly.
- **Approval log**: every `GuardedTransfer` event records `approvedBy` (voice, double-blink, button).

Even if the AI is tricked into asking for too much, the contract refuses. Tested live on testnet: over-limit sends, unknown contacts, a raw address in trusted-only mode, a paused agent, a revoked agent, and a removed contact all **revert on-chain**.

## Run it yourself (macOS, about 5 minutes)

You need: Python 3.11–3.13, an [OpenAI API key](https://platform.openai.com/api-keys), and a **throwaway** Monad testnet wallet funded from the [faucet](https://faucet.monad.xyz).

```bash
git clone https://github.com/callmeharshh/halo
cd halo
./setup.sh                # creates .venv, installs everything, creates .env
# edit .env: set OPENAI_API_KEY and WALLET_PRIVATE_KEY (a throwaway testnet key, never a real one)
source .venv/bin/activate
python doctor.py          # preflight: keys, network, contract, mic, camera, permissions (fix any ❌)
python setup_vault.py     # solo mode: deposits MON into YOUR vault on the deployed contract, sets limits, adds a demo contact "alice"
python halo.py            # opens the Halo interface in your browser (http://127.0.0.1:8765)
```
(`python main.py` is the older desktop window, kept as a fallback.)

**Family mode (recommended story):** instead of `setup_vault.py`, open the **Family** tab in the app, copy the device address or send the pairing link to your family member on WhatsApp, connect their MetaMask and press *Make this wallet the owner of this device and approve it* (this also saves `VAULT_OWNER` for you). Or do it by hand with the public [Family Console](https://callmeharshh.github.io/halo/console.html), connect the family wallet, deposit, set limits, add contacts and paste the device address under *Approve the assistant's device*.

In the browser, press the **Microphone** button (or the **M** key) and try: *"What's my balance?"*, *"Open Calculator"*, *"What's on my screen?"*, *"Send 0.1 MON to Alice"* → *"confirm"*. You can also type commands in the box at the bottom.

**macOS permissions** (System Settings → Privacy & Security), granted to the app you launch from (Terminal / VS Code): **Microphone**, **Camera** (eye tracking), **Accessibility** (mouse and keyboard control), **Screen Recording** (vision).

**Eye tracking:** click *Calibrate eye tracking* (about 1 minute), then toggle *Gaze cursor*. A short blink clicks, a half-second blink right-clicks, and a **double-blink approves a pending payment**.

**Deploy your own contract (optional):** `python contracts/deploy.py` then `python contracts/verify.py` (Sourcify).

### Fully local mode (no cloud LLM)

Halo can also run entirely on-device with **Gemma 4 E4B** through llama.cpp, as the original GemGuide does:

1. Download the [llama.cpp macOS arm64 release](https://github.com/ggml-org/llama.cpp/releases) into `llamacpp/`.
2. Download into `model/`: `gemma-4-E4B-it-Q4_K_M.gguf` and `mmproj-F16.gguf` from [unsloth/gemma-4-E4B-it-GGUF](https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF) (rename to `google_gemma-4-E4B-it-Q4_K_M.gguf` and `mmproj-google_gemma-4-E4B-it-f16.gguf`), plus [`chat_template.jinja`](https://huggingface.co/google/gemma-4-E4B-it).
3. Set `LLM_BACKEND=local` (and optionally `STT_BACKEND=parakeet`) in `.env`.

We measured this on a 16 GB M-series Mac: the model loads in about 13s and handles routing and tool calls correctly (about 2–12s per command). Cloud is the default because it is faster and lighter on RAM.

## Project layout

| File | Purpose |
|---|---|
| `halo.py` + `ui/` | The Halo interface: local web server + browser UI (companion screen, confirmation card, Family tab with MetaMask) |
| `main.py` | Older desktop window (fallback) |
| `doctor.py` | Preflight checker to run before a demo |
| `agents.py` | Orchestrator, System/Vision/Writer/Wallet agents, Guardian confirmation gate, transcribe mode |
| `wallet.py` | Monad layer: reads vault/policy, resolves on-chain contacts, sends via `guardedSend` |
| `voice.py` | Mic capture, WebRTC VAD, speech-to-text (OpenAI or local Parakeet), macOS TTS |
| `safety.py` | Payment safety: speech-vs-amount cross-check, phonetic contact matching, English/Hindi confirm classifier (unit-tested) |
| `gaze.py` | EyeTrax gaze cursor, Kalman smoothing, blink click, double-blink confirm |
| `system_tools.py` | macOS tools used by the agents |
| `server.py` | Launches the optional local llama.cpp server |
| `contracts/` | `GuardVault.sol`, `deploy.py`, `verify.py`, `deployment.json` (address + ABI) |
| `docs/` | The public website (GitHub Pages): live on-chain feed + the Family Console (`console.html`) |
| `demo/` | Fictional scam message for the Scam Shield demo |
| `tests/`, `scripts/` | Regression suite (`scripts/check_all.py`), site/feed helpers (`sync_site.py`, `snapshot_feed.py`) |

## Credits

Halo builds on **[GemGuide](https://github.com/Sourajit1234/GemGuide)** by Sourajit (Gemma 4, EyeTrax gaze tracking, Parakeet speech-to-text, llama.cpp), whose voice, gaze and screen-vision foundation we ported to macOS. All credit for that foundation goes to the original author.

**What we added at Monad Blitz Pune V3:** the multi-agent architecture (Orchestrator + specialists), the Guardian human-confirmation gate (voice / double-blink / button) with speech-error safeguards, the `GuardVault` smart contract (family-owned vault, on-chain policy, pause/revoke, approval log), the Family Console, the Scam Shield, Hindi/Hinglish support, the Monad wallet integration, the macOS port, the OpenAI/local backend switch, and the public website.

## Safety notes

Testnet only. Use a throwaway key, never a wallet that holds real funds. `.env` is git-ignored. Not financial advice.
