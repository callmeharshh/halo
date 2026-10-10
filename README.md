# Halo

**Hands-free computing. Hands-free money. Guarded on-chain.**

Halo is a voice and eye-gaze controlled desktop assistant for people who cannot use a keyboard or mouse. A team of AI agents runs the computer, and a **smart contract on Monad, not the AI, has the final say on every payment.**

Built at **Monad Blitz Pune V3**.

| | |
|---|---|
| **Live site** | https://callmeharshh.github.io/halo/ (live on-chain feed of real payments) |
| **GitHub repo** | https://github.com/callmeharshh/halo |
| **Contract (Monad Testnet)** | [`0x3e89164abbc8852955F179D964B696a4b713418A`](https://testnet.monadscan.com/address/0x3e89164abbc8852955F179D964B696a4b713418A) |
| **Verified source** | [MonadVision (Sourcify)](https://testnet.monadvision.com/address/0x3e89164abbc8852955F179D964B696a4b713418A) · [Monadscan](https://testnet.monadscan.com/address/0x3e89164abbc8852955F179D964B696a4b713418A) |
| **Deploy tx** | [`0x43356d3c…1921b`](https://testnet.monadscan.com/tx/0x43356d3c4b6240ea3fada7a69ff3e6d68e455ed6a557fd40effa65bfd941921b) |
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
- **Trusted-contacts-only mode**: only pay names saved in your on-chain contact book.
- **On-chain contact book**: *"Alice"* resolves on-chain.
- **Approved agent key**: only the owner or one designated agent key can spend.
- **Approval log**: every `GuardedTransfer` event records `approvedBy`.

Even if the AI is tricked into asking for too much, the contract refuses. Tested live on testnet: a 0.6 MON send against a 0.5 MON cap, an unknown contact, and a raw address in trusted-only mode all **revert on-chain**.

## Run it yourself (macOS, about 5 minutes)

You need: Python 3.11–3.13, an [OpenAI API key](https://platform.openai.com/api-keys), and a **throwaway** Monad testnet wallet funded from the [faucet](https://faucet.monad.xyz).

```bash
git clone https://github.com/callmeharshh/halo
cd halo
./setup.sh                # creates .venv, installs everything, creates .env
# edit .env: set OPENAI_API_KEY and WALLET_PRIVATE_KEY (a throwaway testnet key, never a real one)
source .venv/bin/activate
python setup_vault.py     # deposits MON into YOUR vault on the deployed contract, sets limits, adds a demo contact "alice"
python main.py
```

Click **START LISTENING** and try: *"What's my balance?"*, *"Open Calculator"*, *"What's on my screen?"*, *"Send 0.1 MON to Alice"* → *"confirm"*. You can also type commands in the box at the bottom.

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
| `main.py` | Desktop UI: agent activity feed, vault panel, Guardian buttons, mic and gaze controls |
| `agents.py` | Orchestrator, System/Vision/Writer/Wallet agents, Guardian confirmation gate, transcribe mode |
| `wallet.py` | Monad layer: reads vault/policy, resolves on-chain contacts, sends via `guardedSend` |
| `voice.py` | Mic capture, WebRTC VAD, speech-to-text (OpenAI or local Parakeet), macOS TTS |
| `gaze.py` | EyeTrax gaze cursor, Kalman smoothing, blink click, double-blink confirm |
| `system_tools.py` | macOS tools used by the agents |
| `server.py` | Launches the optional local llama.cpp server |
| `contracts/` | `GuardVault.sol`, `deploy.py`, `verify.py`, `deployment.json` (address + ABI) |
| `docs/` | The public website (GitHub Pages) with a live on-chain feed |

## Credits

Halo builds on **[GemGuide](https://github.com/Sourajit1234/GemGuide)** by Sourajit (Gemma 4, EyeTrax gaze tracking, Parakeet speech-to-text, llama.cpp), whose voice, gaze and screen-vision foundation we ported to macOS. All credit for that foundation goes to the original author.

**What we added at Monad Blitz Pune V3:** the multi-agent architecture (Orchestrator + specialists), the Guardian human-confirmation gate (voice / double-blink / button), the `GuardVault` smart contract with on-chain policy and approval log, the Monad wallet integration, the macOS port, the OpenAI/local backend switch, and the public website.

## Safety notes

Testnet only. Use a throwaway key, never a wallet that holds real funds. `.env` is git-ignored. Not financial advice.
