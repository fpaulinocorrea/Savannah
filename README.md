# Savannah

Guest replies + bookkeeping for your rentals. Runs on this computer, opens on any screen.

## ▶️ Start it

Open **Terminal** in this folder and run:

```
bash install-autostart.sh
```

Do this **once**. After that, Savannah starts on its own whenever the computer turns on.
Open it from your app menu (search **Savannah**).

Just want to try it without auto-start? Run `bash start.sh` instead.

## 📱 On your phone

In Savannah, go to **Settings → Open on your phone** and scan the QR code.
Your phone needs to be on the same Wi-Fi.

## 💬 Guest replies (phase 2)

1. **Settings → Connections**: paste your Hospitable key and your Claude key.
2. Savannah learns from your last two years of conversations (you'll see a progress bar).
3. Every 5 minutes it checks for guests waiting on a reply and drafts one in your voice.
4. In **Guests**: read it, edit if you like, then **Send**. Or tap **Shorter**, **Warmer** or **More detail**.

If a draft has a note like **[ADD: wifi password]**, Savannah didn't know that detail. Fill it in before sending.
Nothing is ever sent without your tap. Every reply you send is saved to `data/conversations/`, so drafts keep improving.

## 🏦 Books (phase 3)

1. **Settings → Connections**: paste your Plaid client ID and Production secret.
2. Put your QuickBooks exports in the `imports` folder (Account List + Transaction List by Date, as Excel).
3. **Books → Setup**: import the Account List, then look at the history preview and import it.
4. **Books → Connect Chase**: sign in to Chase in Plaid's window. Savannah fetches up to 2 years and updates every 6 hours.
5. **To review**: check Savannah's guesses, tick **Always do this** to make a rule.

Sorting order: your rules → what you did before → Claude's guess (always shown for review).
Bank transactions before the **start date** are hidden, because QuickBooks history already covers them.

## 🗂️ What's in this folder

| Folder | What it is | Language |
|---|---|---|
| `server/` | The engine: sign-in, Hospitable + AI drafts (`sync.py`, `drafting.py`), books (`ledger.py`, `plaid.py`, `quickbooks.py`, `categorize.py`) | Python |
| `imports/` | Drop QuickBooks exports here (private, never shared) | — |
| `web/src/` | The screens you see | TypeScript (React) |
| `web/dist/` | The screens, ready to show (built from `web/src`) | — |
| `data/` | **Your private data.** Back up this folder. Created on first start. | — |

Good files to start reading: `server/app.py`, then `web/src/pages/Home.tsx`.

## 🛠️ Handy commands

| To… | Run |
|---|---|
| Stop auto-start | `bash remove-autostart.sh` |
| Restart Savannah (also loads a new version) | `systemctl --user restart savannah` |
| See if it's running | `systemctl --user status savannah` |
| Rebuild the screens after changing `web/src` | `cd web && npm install && npm run build` |

## 🧭 Build progress

- [x] Phase 1: Foundation
- [x] Phase 2: Guest replies (suggest mode)
- [x] Phase 3: Bank and categories
- [ ] Phase 4: Reports and invoices
- [ ] Phase 5: Auto-reply and cloud
