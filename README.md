# ContextCare AI

A local-first, **working educational prototype** of a privacy-aware conversational assistant for a computational-linguistics final-year project. It provides real SQLite persistence, encrypted identity storage, a trained offline intent model, heuristic NLP, memory lookup, task/reminder state, Streamlit, and an authenticated FastAPI server.

## Start in Windows (3 steps)
1. Install **Python 3.11 or newer** from python.org and select **Add Python to PATH**. A working internet connection is required **on first setup** to install Python packages.
2. Extract the ZIP to a writable folder such as `Documents\ContextCare_AI`.
3. Double-click **`run.bat`**. On first use it creates `.venv`, installs dependencies, and trains the model (if necessary), then starts Streamlit. Visit the local address printed in the window (normally `http://localhost:8501`). Keep the console open.

Create an account using a username and an 8+-character password. Subsequent launches reuse the environment. If `py` is unavailable, install the Python Windows launcher. Run `setup.bat` manually if setup fails; `run_tests.bat` executes automated tests. `run_api.bat` starts Swagger-enabled FastAPI at `http://127.0.0.1:8000/docs`.

## Try the Trishanth scenario
1. In **AI Chat**, enter: `My name is Trishanth. I am preparing for my CAT exam, and I have a meeting with Rahul tomorrow at 4 PM.`
2. Inspect the masked message/aliases, and visit **Tasks & Reminders** to see the persisted meeting.
3. Ask `Remind me about that meeting` and then `What is my name?`. The latter reveals the original to the currently authenticated owner, but the unmasked reply is not persisted in the conversation database.
4. Explore **Privacy Dashboard**, **Semantic Memory Search**, and **NLP Analysis**. Reminder notices appear *inside* the app, not via external notifications.

## What is included
- Auth: salted scrypt hashes, opaque random session tokens (hashes in DB), 7-day expiry, temporary lockout.
- Privacy: NER + regex masking **before conversation persistence**, consistent per-account aliases, AES-256-GCM vault, HMAC blind lookup, key rotation, authenticated reveal, masked analytics.
- NLP: optional locally-installed spaCy model with always-on rules; relative date/time parser; optional trained TF-IDF word/character Logistic Regression; lexicon-based sentiment.
- Conversation: persisted slot-filling and confirmation state; heuristic mention resolution using active tasks; masked long-term memory, hashing vectors and cosine search.
- Streamlit: 10 navigable screens. FastAPI: endpoints documented in `/docs`; basic owner scoping.
- Tests/reports: `pytest`, trained synthetic dataset, classifier report, confusion matrix PNG, evaluation JSON.

## Security notice
The app is **not a production-grade privacy guarantee**. Pattern and statistical NER miss some PII; usernames are identifiers; passwords, recovery, backup, key custody and deployment controls require additional work. Encrypted vault keys are stored in an adjacent local `.key` file by default; protect this file separately. Do not upload your database, key or raw data to public repositories. Pseudonymisation is reversible and not anonymisation.

## Troubleshooting
- `py is not recognized`: install Python + the Windows launcher, then reopen the terminal.
- Package installation fails: check internet access / Python version / corporate proxy. Run `setup.bat` again.
- Browser does not open: manually open `http://localhost:8501` after running `run.bat`.
- Missing key with existing vault: **restore the original `.key`** from a secure backup; the app deliberately stops instead of overwriting it.
- Model incompatible with local scikit-learn: run `scripts\train.py` using your `.venv\Scripts\python.exe` to retrain.
- To preserve accounts/identity mappings, back up **both** `data\contextcare.db` and `data\contextcare.key` in secure storage. They are excluded from distributed ZIPs.

## Important limitations
See `docs/LIMITATIONS.md` and `docs/EVALUATION.md`. The project is an educational implementation and **does not fully satisfy every ambitious research-grade requirement of the original specification**. In particular, model evaluation remains weak on unseen templates. No real neural coreference or production-grade PII-DLP guarantee is claimed.
