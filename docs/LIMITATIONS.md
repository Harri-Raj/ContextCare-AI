# Engineering limitations and unimplemented research ambitions

This is a functioning **educational prototype**, not a research-grade NLP solution or security-certified assistant. All claims below describe the delivered code.

- **Entity detection:** explicit self-name and meeting-with patterns, regex email/phone/address/IDs, exam/event lexicons, optional spaCy model. Many unseen phrasings and names are missed. Gazetteer is limited. The optional spaCy model is not bundled.
- **Intent classification:** 17 labels trained on 6,200 synthetic augmented utterances. Holdout groups prevent base-template variants crossing the split but provide severe domain shift; see actual score in `reports/intent_metrics.json`. Confidence is not calibrated. A few high-precision rules bypass the classifier.
- **Coreference:** active-task heuristic plus simple mention patterns; it is not comprehensive salience, generalized pronoun resolution, cross-session ambiguity handling, or neural coreference.
- **Memory:** 256-feature hashing vectors + cosine and keyword matching; no packaged sentence-transformer, no robust contradiction detector, consent retroactive purge, conversation summarizer, memory edit screen or adaptive retrieval reranker.
- **Task/meeting engine:** works for certain full date/time expressions and slot-filling; time zone defaults to the host runtime environment, not the user's geolocation. It stores reminders but only notifies in app; not background scheduling, SMS, push or email. Natural language edits/deletions focus on the most recent active task.
- **Temporal parsing:** limited supported dates and formats; DST, timezone inference, nuanced recurring expressions and ambiguity handling are incomplete.
- **UI:** all 10 screens exist, but feedback thumbs, full memory editing, production deletion confirmations, separate private original-export flow and plotted monitoring analytics are not included. Use masked export. Some buttons use immediate user intent rather than a second confirmation step.
- **Database:** migrations include an initial version only. Using SQLite does not make the schema directly PostgreSQL-executable (notably PRAGMAs and `BLOB`).
- **Testing:** tests run in Linux/Python 3.13 in this environment. Streamlit was unavailable to run here, and full Windows double-click startup was not tested. No mocked Streamlit smoke test, comprehensive failure injection, broad privacy corpus or independent public benchmark was run.
- **Deployment/security:** no production-grade PII prevention guarantee, hardened security boundary, secret manager, multitenant production load design or production backups.

For a viva, describe each heuristic accurately and identify these as prospective enhancements, not completed achievements.
