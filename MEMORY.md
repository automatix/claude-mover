# MEMORY.md

## `2026-05-05` – Projektstart

**Request:** Initiale Konversation lesen und Projekt aufsetzen (`/init`).

**Done:**
- `Initial Conversation.md` gelesen (Domänenwissen: Claude Code Pfad-Kodierung, korrekter Migrations-Ablauf).
- `CLAUDE.md` mit Projektbeschreibung und Domänenwissen erstellt.
- Git-Repository initialisiert.
- `.gitignore`, `README.md`, `MEMORY.md` erstellt.

**Result:** Projekt ist versioniert und bereit für die Implementierung.

## `2026-05-06` – Anforderungserhebung

**Request:** Anforderungen für das Tool interaktiv erheben.

**Done:** Vollständige Anforderungen erhoben.

**Ergebnis:**

| # | Anforderung | Entscheidung |
|---|---|---|
| 1 | Plattform | Windows |
| 2 | Interface | CLI |
| 3 | Sprache | Python, Standalone-Script |
| 4 | Aufruf | `claude-mover <quelle> <ziel>` |
| 5 | Pfadformate | CMD-Style, Git-Bash-Style, Claude-Dashed-Style |
| 6 | Dry-run | `--dry-run`-Flag |
| 7 | Backup | Vor dem Verschieben, Cleanup nach Erfolg |
| 8 | Ziel existiert | Abbruch mit Fehlermeldung + Handlungsanweisung |
| 9 | Elternverzeichnis fehlt | User fragen: abbrechen / anlegen / selbst anlegen + retry |
| 10 | Quell-Validierung | Ordner + Claude-Kontext müssen existieren |
| 11 | Ziel-Validierung | Claude-Kontext darf nicht bereits existieren |
| 12 | Config-Patching | Alle Strings in `.claude/settings.json`, `.mcp.json` |
| 13 | `history.jsonl` | Pfadreferenzen aktualisieren |
| 14 | Logging | `%LOCALAPPDATA%\ClaudeMover\logs\` |
| 15 | Abschluss | Zusammenfassung: Sessions, gepatchte Dateien, Logpfad |

**Zurückgestellte Features:**
- **Merge-Modus:** Zusammenführen von Claude-Session-Historien zweier verwandter Projektpfade in ein Zielverzeichnis.
- **pip-Package:** Distribution als installierbares Python-Package (`pip install claude-mover`).

## `2026-05-06` – Merge, SemVer-Einführung, Release

**Request:** PR mergen, SemVer einführen, global merken.

**Done:**
- PR [#2](https://github.com/automatix/claude-mover/pull/2) gemergt.
- SemVer eingeführt: `v0.1.0` (erster funktionierender Minor-Release, noch kein stabiles API).
- GitHub Release [v0.1.0](https://github.com/automatix/claude-mover/releases/tag/v0.1.0) mit `claude_mover.py` als Artefakt erstellt.
- SemVer-Regel als globales Memory gespeichert.

**Result:** Projekt ist released und versioniert.

## `2026-06-02` – README usage instructions

**Request:** Add usage instructions to the README.

**Done:**
- Added Requirements, Usage, Path formats, Examples, Rollback, and Logs sections to `README.md`.
- Also committed previously uncommitted changes: `CLAUDE.md` (architecture docs) and `.claude/settings.local.json` (git tag / gh release permissions).
- All changes committed on branch `docs/add-usage-instructions`.

**Result:** `README.md` now documents how to run the tool, all supported path formats, example invocations, and rollback/log behaviour.
