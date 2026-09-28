# The one-click trade whisper (`scripts/whisper.py`)

The **Trade Orders** tab can put one warframe.market whisper into the running game with one
click per row. This page is what that button actually does, what it refuses to do, and what
breaks when the game is not running.

Nothing here is loaded at dashboard start: the module is stdlib + `ctypes` only, importing
it opens no DLL, and the first thing that happens on a click is a clipboard write.

## What one click does

1. `message(item, price, kind, rank)` builds the standard warframe.market line.
2. `copy(text)` puts it on the Windows clipboard as `CF_UNICODETEXT` (`OpenClipboard` /
   `EmptyClipboard` / `SetClipboardData` / `CloseClipboard`, retried briefly if another app
   is holding the clipboard).
3. `send(text)` finds the Warframe window (`EnumWindows` + `GetWindowTextW`), brings it to
   the front, and types **Ctrl+V** then **Enter** with `SendInput` — the recipe AlecaFrame
   uses for its one-click whisper.

That is the whole feature: one call, one message, one row in the log.

## The message

```
buying : Hi! I want to buy: "<item>" for <price> platinum. (warframe.market)
selling: Hi! I am selling: "<item>" for <price> platinum. (warframe.market)
```

* `kind` accepts `buy` / `buying` / `wtb` and `sell` / `selling` / `wts` (case-insensitive).
  Anything else raises `ValueError` rather than guessing.
* A `rank` above 0 is added as ` rank <n>` immediately before ` for`; **rank 0 or no rank
  adds nothing**:

  ```python
  message('Primed Continuity', 120, 'sell', 10)
  # Hi! I am selling: "Primed Continuity" rank 10 for 120 platinum. (warframe.market)
  message('Primed Continuity', 120, 'sell', 0)
  # Hi! I am selling: "Primed Continuity" for 120 platinum. (warframe.market)
  ```

* The doubled quotes around the item and the `(warframe.market)` tail are kept exactly as
  they are: warframe.market's terms ask for its copy/paste message to be sent unmodified,
  which is also what makes the message recognisable to the other trader.
* A JSON float price prints as an integer (`120.0` → `120`), so a price straight out of
  `data/` never shows up as `120.0` in game.

## The click-per-message discipline

There is **no queue, no loop, no batch mode, no retry and no "send to everyone"** in this
module. Sending whispers at machine speed is how accounts get ignored or reported, so the
module paces itself and the tab must not fight it:

| Guard | Value | Behaviour |
| --- | --- | --- |
| Cooldown | 2 s between two sends | second click answers `cooldown 2s`, nothing copied, one log row |
| Minute cap | 10 sends / 60 s | the 11th answers `rate limit 10 per minute`, nothing copied |
| Trigger | the user's click | the dashboard never sends on a timer, on a refresh or in a loop |

Refused attempts are **not** silent: every one of them is appended to the ledger, so the tab
can say *why* nothing happened. Only a message that really left the machine counts against
the cap. If a click is refused, the line is still on screen in the tab — copy it and paste
it into chat yourself; the game is not owed anything.

## What it cannot do without the game running

| Situation | What the user gets | What did **not** happen |
| --- | --- | --- |
| Warframe not running | `(False, 'game window not found')` **and the text is on the clipboard** | nothing was typed anywhere |
| Clipboard held by another app | `(False, 'clipboard busy')` | nothing typed, nothing copied |
| Game window found but it will not come to the front | `(False, 'game window not focused')` | **nothing typed** — the text is on the clipboard |
| `SendInput` refused (see UIPI below) | `(False, 'input blocked')` | nothing typed |
| Not Windows at all | `(False, 'windows only')` | nothing copied, nothing typed |
| Empty message text | `(False, 'empty message')` | nothing copied |

`probe()` answers `{'game': bool, 'reason': str}` without touching the clipboard or the
keyboard, so the tab can grey the button out with a reason instead of guessing.

Two things it deliberately will not do:

* **Type without confirming the foreground window.** Windows refuses `SetForegroundWindow`
  from a background process (the click happened in the browser, not in the dashboard
  process), so the module attaches to the foreground thread first *and then verifies* that
  the game really is the foreground window. If it is not, the send is refused — pasting a
  whisper into Discord, into a warframe.market tab, or into the game **launcher** (whose
  Enter button is "Play") is worse than not sending at all. Browser, launcher and Overwolf
  windows are skipped by title **and** by process name.
* **Do anything but chat input.** The keystrokes are exactly `Ctrl` down, `V` down, `V` up,
  `Ctrl` up, `Return` down, `Return` up. No movement, no abilities, no trade-window
  automation, no order management; the whisper only lands because the user clicked.
* **Open the chat box for you.** With the in-game chat closed, Warframe swallows the paste
  and that trailing `Enter` only opens the chat box — nothing is sent, and the line is still
  on the clipboard. Press `Enter` in game once (or `T` for trade chat) before clicking; the
  dashboard deliberately types no extra keys into the game.

## The ledger (`data/whisper_log.json`)

Every call to `send()` appends exactly one row — sent, refused, or off Windows:

```json
{"ts": "2026-09-28T11:25:31Z", "user": "RoyalSpartanIIX", "item": "Primed Continuity",
 "price": "120", "kind": "buy", "mode": "copy", "copied": true, "sent": false,
 "reason": "game window not found"}
```

* `mode` is `sent` (copied **and** typed), `copy` (copied only — paste it yourself),
  `blocked` (a guard refused; nothing copied) or `unsupported` (not Windows).
* `user` is added only when `data/trader_state.json` names the account; it is never invented.
* Writes are atomic (`tmp` + `os.replace`) and the newest **500** rows are kept. A corrupt
  file is moved aside to `whisper_log.json.corrupt-<stamp>` and a fresh ledger starts — the
  log is the record of what was typed, so it is never silently truncated.

## Interface

```python
from scripts import whisper            # scripts/ has no __init__: import by path in server.py

line = whisper.message('Primed Continuity', 120, 'buy', rank=10)   # what the row shows
whisper.copy(line)                                                 # clipboard only, no log
sent, reason = whisper.send(line, item='Primed Continuity', price=120, kind='buy')
whisper.probe()          # {'game': False, 'reason': 'game window not found'}
whisper.log_last(20)     # newest 20 ledger rows, newest first
```

`send()`'s only required argument is the finished line; `item` / `price` / `kind` / `user`
just enrich the log row — without them the row is filled by parsing the line itself
(`parse()`), so a row written by the tab and a row written by the CLI look the same.

`find_game()` returns the game's window handle (or `None`), `read()` returns the clipboard's
text, `reset()`/`gate()` exist for tests, and `loaded_libs()` reports which Win32 DLLs the
process has loaded (empty until something is really sent or copied).

## Command line

```
python scripts/whisper.py --selftest
python scripts/whisper.py --message primed_continuity 120 buy --rank 10
python scripts/whisper.py --send 'Hi! I want to buy: "Primed Continuity" for 120 platinum. (warframe.market)'
python scripts/whisper.py --probe
python scripts/whisper.py --log 10
```

`--selftest` is offline and safe to run **with the game open**: it checks the message cases,
the clipboard round-trip (restoring whatever was on the clipboard), the refusal paths, the
ledger rules and both rate gates on a fake clock — but its send checks run against stubbed
window/clipboard seams, so no key is ever typed and no real ledger row is written.

`--message` takes an item **slug** and title-cases it for display (`primed_continuity` →
`Primed Continuity`); the tab always passes the real item name to `message()` instead.
`--send TEXT` is a manual one-message send for a shortcut or a sanity check, `--probe`
answers whether the game window is there, and `--log N` prints the newest ledger rows.

## When it says no (Windows notes)

* **`input blocked`** — Windows blocks `SendInput` from a lower-privilege process into a
  higher-privilege one (UIPI). If the dashboard is running as administrator and the game is
  not (or the reverse), the keys are dropped. Run both the same way.
* **`game window not focused`** — the game refused to come forward (another app stole focus
  during the 2 s, or a fullscreen-exclusive game is not switching). Click into the game
  once, then press the button again; the text is already on the clipboard.
* **`clipboard busy`** — some other app was holding the clipboard for the whole retry
  window; close it and retry.
* **`game window not found`** — the game is not running (or only the launcher is). The text
  is on the clipboard: switch to the game and paste it yourself.
* **The in-game chat box must be open.** The keystrokes are `Ctrl+V` then `Enter` and
  nothing else, so with the chat closed the game swallows the paste and the `Enter` only
  opens the chat box. Press `Enter` in game once (or `T` for trade chat) and click again.
* Warframe has no API for chat input and this module does not look for one: it types the
  same message a human would type after copying it from warframe.market.

## Tests

`tests/test_whisper.py` pins the message wording (rank 0 vs 10), the window-selection rules
(browser / launcher / look-alike windows are never typed into), the exact `Ctrl+V` then
`Enter` event order, every refusal reason, both rate gates on a fake clock, and the ledger
contract (row shape, 500-row cap, atomic write, corrupt file). The real clipboard is
exercised once on Windows; no test types a key or touches the repo's `data/` directory.
