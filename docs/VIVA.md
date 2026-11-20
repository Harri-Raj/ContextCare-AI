# Viva questions & short answers

**Q: What is the objective?** Build an offline-first assistant that stores masked conversational facts, performs tasks, and protects detected identity strings using authenticated encryption.

**Q: Is this anonymisation?** No. It is reversible pseudonymisation: protected originals live in an encrypted identity vault.

**Q: Why AES-GCM?** It encrypts and authenticates data. Wrong key or corrupted ciphertext fails authentication. Per-record nonce and per-record AAD bind ciphertext to user and type.

**Q: What does the blind index do?** HMAC of user ID, entity type and normalized original enables exact deduplicated identity matching without storing the original in an indexed column.

**Q: Where is NER used?** Before message persistence, for span detection and alias substitution; in this build it is primarily rule-based with optional spaCy.

**Q: What ML classifier?** TF-IDF word/character features with Logistic Regression. The ~6,200 labelled items are synthetic, and the grouped heldout accuracy is reported transparently.

**Q: Explain semantic retrieval.** Each masked memory is represented with a 256-dimensional hashing vector and ranked with cosine and keyword overlap; it is approximate lexical semantics, not a deep language embedding model.

**Q: Explain coreference.** Persisted dialogue state tracks an active task, so a follow-up like `that meeting` maps to its stored task ID. General pronoun coreference remains incomplete.

**Q: Can it remind users outside the application?** No. The app queries pending reminders and displays due items on the dashboard.

**Q: What are the biggest weaknesses?** PII detection recall, generalized context resolution, synthetic intent-model generalization, timezone assumptions, and key custody.
