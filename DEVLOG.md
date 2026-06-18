# DEVLOG — Lullaby build journal

Reverse-chronological. Keep entries short: what changed, what was learned, what is next. Canonical decisions and status belong in [memory.md](memory.md).

---

## 18 June 2026 — project pivot

Lab Witness is retired as the main project and preserved under `Archive/`. The repository is now Lullaby, a privacy-first baby-monitor companion.

The active scope is Tier 0 only: process sample audio or a microphone locally, detect sustained crying with YAMNet, write a night log, generate a rule-based morning digest, and send one debounced notification. Development starts on a laptop with no nursery hardware attached.

**Next single outcome:** run the included sample recording end-to-end and open the generated log and digest.
