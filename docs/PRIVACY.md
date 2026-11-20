# Privacy, data security and threat model

## Provided protections
- The message path detects identity text **before** storing masked conversation text; original detected names/emails/phones/address/IDs are stored as AES-256-GCM ciphertext. Each record uses a random nonce, owner/type authenticated associated data, and HMAC blind lookup.
- Deterministic per-user aliases resolve consistently to one vault record. Repeated aliases are not reclassified as real names in task titles.
- Account passwords use per-user salted scrypt. Sessions use SHA-256 token digests, expire, and can be revoked. Cross-user conversation/history operations validate owner identity.
- User messages are never printed to the app logger. Audits store operation names, not original identity text.
- `reveal_originals` is a **privileged** operation: the identity is briefly decrypted in memory, and audit trail records reveal use. The app's History screen requires password recheck; standalone `Privacy.reveal()` must only be invoked after proper authentication in a trusted service.

## Not provided / threats
- PII detection is **best effort**. Unrecognized names, bank details, identifiers, URLs, arbitrary personal details or user-contributed free text can leak into SQLite or display. This is **not a verified zero-PII leakage system**.
- A stolen database **plus the adjacent `.key` file** allows vault decryption. Protect keys in separate secrets management for production. In-process attackers can observe plaintext during ingestion.
- Usernames are plaintext login handles, and may be personal names. SQLite may hold account metadata and unmasked data if bypassing the service. OS swap, terminal traceback, user exports, filesystem backups, or malicious extensions are out of scope.
- No browser/session CSRF hardening, TLS proxy, production rate limiting, distributed session store, external push, separate backup encryption, compliance certification, or disaster recovery.
- An alias is a **pseudonym**, and the vault supports reversal. This is not anonymisation. Exported plaintext can be copied by the user; avoid exposing export files.
- Removing an account deletes current relational records, but does not sanitize filesystem snapshots, WAL remnants or backups. SQLite byte-scanning tests are only narrow checks of seeded names.

## Scope of privacy validation
`tests/test_core.py` checks seeded raw names are absent from the current SQLite file, cross-account scoping, wrong-key and tampered ciphertext, key-rotation and missing-key refusal. This is not a general proof about all possible text or all storage environments.
