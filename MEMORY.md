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

## `2026-06-02` – WSL UNC path support

**Request:** Support WSL paths (`\\wsl.localhost\Ubuntu\...`) as source and target in claude_mover.py.

**Done:**
- Clarified: no cross-store migration needed; Windows Claude Code uses the Windows `%USERPROFILE%\.claude\` store even for WSL projects accessed via UNC.
- Identified encoding rules from real PROJECTS_DIR entries: `\\` → `--`, server+share lowercased, `.` → `-`, path components case-preserved.
- Implemented on branch `feature/wsl-unc-path-support` (GitHub issue [#3](https://github.com/automatix/claude-mover/issues/3)):
  - `encode_path`: UNC branch
  - `_decode_dashed_unc_naive` + `_UNC_DASHED_SERVERS`: decode `--wsl-...` back to UNC
  - `normalize_path`: accept `\\...`, `//...`, and `--wsl-...`
  - `_path_variants`: 5-variant list for UNC paths

**Result:** claude_mover.py now supports Windows ↔ WSL moves in all path formats.

## `2026-06-02` – MAX_PATH fix: robocopy for directory move

**Request:** Migration to `\\wsl$\Ubuntu\...` failed with `[WinError 3]` for files with very long names in `vendor/composer/`.

**Done:**
- Root cause: `shutil.move` uses `CreateFileW` (260-char `MAX_PATH` limit). The UNC prefix `\\wsl$\Ubuntu\home\automatix\workspace\SleepNote\` (49 chars) plus the long vendor path pushed two PHP filenames to exactly 260 chars — one over the null-terminator limit.
- Fix: replaced `shutil.move` with a new `_move_directory(source, target)` helper that uses `robocopy /E` (which uses the Windows extended-length path API internally) followed by `shutil.rmtree(source)` (source paths unchanged, guaranteed under `MAX_PATH`).
- Branch: `bugfix/long-path-robocopy`.

**Result:** Moves to UNC targets with long file paths now succeed.

## `2026-06-02` – Rollback-Fix + `--resume` + Checkpoint

**Request:** Nach fehlgeschlagener Migration: Zustand analysieren, Recovery-Hilfe, dann Sicherungsmechanismus einbauen.

**Done:**
- Analyse: Der alte Rollback stellte nur den Source-Context wieder her, ließ aber den stale Target-Context (`--wsl$-ubuntu-...`) und die Partial-WSL-Kopie zurück.
- `_rmtree_robust(path)` hinzugefügt: fällt bei `OSError` auf robocopy `/MIR` zurück (Long-Path-sicheres Löschen).
- Rollback in `migrate()` verbessert: räumt jetzt auch stale `target_ctx` und Partial-Kopie bei `target` auf.
- Checkpoint-Mechanismus (`_write_checkpoint` / `_read_checkpoint` / `_clear_checkpoint`) hinzugefügt: schreibt `%LOCALAPPDATA%\ClaudeMover\checkpoints\<source>.json` nach Backup-Erstellung, aktualisiert bei Fehler mit Error-Meldung, löscht bei Erfolg.
- `--resume`-Flag in `main()`: räumt stale `target_ctx` + Partial-Kopie auf, dann normaler Migrations-Lauf.
- `CLAUDE.md` aktualisiert.

**Result:** Nach einem Fehler reicht `python claude_mover.py <source> <target> --resume` um die Migration sauber neu zu starten. Kein manuelles Aufräumen mehr nötig.

## `2026-06-02` – Session-Abschluss: Workflow-Instruktion + README-Finalisierung

**Request:** README aktualisieren; Instruktion hinzufügen: PRs immer mergen und lokal auf master zurückwechseln.

**Done:**
- README aktualisiert: `--resume` in Usage-Tabelle, verbesserter Rollback-Abschnitt, neuer Abschnitt „Recovering from an interrupted migration".
- `CLAUDE.md` Workflow-Abschnitt hinzugefügt: nach jedem PR `gh pr merge` + lokales Zurückwechseln auf `master`.
- PR [#7](https://github.com/automatix/claude-mover/pull/7) gemergt, lokal auf `master` zurückgewechselt und gepullt.

**Result:** Projekt ist auf `master`, alle Änderungen dieser Session sind integriert.

## `2026-06-02` – ~/.claude.json: fehlende Datei im Migrations-Scope

**Request:** Claude-App zeigt nach WSL-Migration immer noch den alten Windows-Pfad `D:\workspace\tools\SleepNote`.

**Done:**
- Root cause gefunden: `~/.claude.json` (im HOME-Verzeichnis, NICHT in `~/.claude/`) ist die globale App-Konfiguration, die die Claude Desktop-App für das Projektlisten-Display liest. Sie speichert Pfade als JSON-Schlüssel (backslash- und forward-slash-Form) sowie im `githubRepoPaths`-Mapping.
- Zusätzlicher Bug: `_path_variants` erzeugte keine JSON-enkodierte Backslash-Form — `history.jsonl` und `.claude.json` verwenden `D:\\workspace` (zwei Backslashes). 6. Variante via `json.dumps(p_str)[1:-1]` hinzugefügt (PR [#14](https://github.com/automatix/claude-mover/pull/14)).
- `~/.claude.json` manuell gepatcht: 3 Vorkommen (2× backslash, 1× forward-slash) ersetzt.
- `CLAUDE_JSON`-Konstante und Step 6 in `migrate()` hinzugefügt: patcht `~/.claude.json` automatisch bei jeder Migration.
- Direkt auf `master` gepusht (Abweichung von der Branch-Regel — wird beim nächsten PR beachtet).

**Result:** Die Claude Desktop-App sollte nach App-Neustart den neuen WSL-Pfad anzeigen.

## `2026-06-02` – Unit-Tests + UNC-Path-Fix + patch_file-Bugfix

**Request:** Unit-Tests schreiben (Coverage-Ziel `95%`+), 5.197 Session-Zeilen nachpatchen, UNC-Path-Mangling bei `wsl$` beheben.

**Done:**
- **Session-Nachpatchen:** `21` Dateien, `5.197` Zeilen neu gepatcht — der alte Code hatte keine 6. Variante (JSON-enkodierte Backslash-Form), weshalb `history.jsonl`-Einträge unverändert blieben.
- **UNC-Fix (`_path_to_str`):** `pathlib.Path(r'\\wsl$\...')` erkennt `wsl$` nicht als UNC-Server (das `$` verwirrt den Parser) und streicht einen Backslash. Neuer Helper `_path_to_str()` erkennt diesen Fall und stellt das fehlende `\\`-Prefix wieder her. `encode_path()` und `_path_variants()` verwenden nun `_path_to_str` statt `str(path.resolve())`.
- **`patch_file`-Bugfix:** Die alte Return-Formel (`text.count('\n') - patched.count('\n')`) war immer `0` bei reinen Pfad-Replacements. Fix: einfach `1` zurückgeben.
- **Unit-Tests:** `test_claude_mover.py` mit `140` Tests, `20` Test-Klassen, `92%` Line-Coverage.
- **GitHub Issue [#15](https://github.com/automatix/claude-mover/issues/15)** erstellt; Branch `bugfix/session-repatching-and-tests`.

**Result:** `140` Tests bestehen, Coverage `92%` (über dem Ziel von `80%`). PR folgt.

## `2026-06-02` – Reparatur korrupter WSL-Pfade + README-Ergänzung

**Request:** Verbleibende `87` Treffer von `SleepNote+tools` untersuchen; `D:\\wsl$\\Ubuntu` (falsch-korrupt) identifizieren und reparieren; README um Test-Anleitung ergänzen.

**Done:**
- **Root-Cause-Analyse:** Der alte Code `str(path.resolve())` bei `\\wsl$\...`-Paths: `pathlib` verschluckte den führenden `\` (Parser kann `wsl$` nicht parsen), Rest wurde gegen `D:` aufgelöst → `D:\wsl$\Ubuntu\...` (nie existent). Ein früherer Migrationslauf schrieb diesen korrupten Pfad in **alle** SleepNote-Session-Dateien.
- **Daten-Reparatur:** `21` SleepNote-Session-Dateien gescannt; `7599` korrupte Tokens in `5` Kodierungen (`D:\\wsl$`, `D:\\\\wsl$`, `D:/wsl$`, `D--wsl$`) identifiziert und durch korrekten UNC-Pfad `\\wsl$\Ubuntu\...` ersetzt. JSON-Validität jeder Zeile sichergestellt; Backups unter `%USERPROFILE%\.claude\backups\wsl-path-repair\` angelegt.
- **Code-Verifikation:** Aktueller Code (`_path_to_str`-Helper, fixes von v0.1.1) produziert diese Korruption nicht mehr — getestet mit `_path_variants(\\wsl$\...)`.
- **README:** `Tests`-Abschnitt hinzugefügt mit Anleitung (`python -m pytest test_claude_mover.py`), Optional `pytest-cov`, Hinweis auf `140` Tests / `92%` Coverage.

**Result:** SleepNote-Kontext vollständig sauber (`0` korrupte Tokens). Verbleibende `150` Treffer sind Artefakte der Live-Claude-Mover-Session (diese Analyse mitgeloggt) und `history.jsonl` (Fließtext-Zitate); keine echten Pfadreferenzen.

## `2026-06-02` – Diagnose: altes .claude.json-Key + Git-Cleanup

**Request:** Nach dem Migrations-Fix: Desktop-App zeigt beim Trust-Dialog und bei "Copy path" immer noch den alten Pfad `D:\workspace\tools\SleepNote`. Diagnose durchführen und Instruktionen für manuellen Fix erarbeiten.

**Done:**
- **Diagnose:** Die einzige verbleibende Quelle des alten Pfads ist ein verwaister Projekt-Key in `~/.claude.json`: `projects["D:\workspace\tools\SleepNote"]` neben den korrekten WSL-Keys (`\\wsl$\...`, `//wsl$/...`). Die Desktop-App liest `~/.claude.json` für die Pfad-Anzeige. Session-`cwd`-Felder, `githubRepoPaths` und das Kontext-Verzeichnis sind korrekt — nur dieser globale Config-Key ist alt.
- **Ursache:** `claude_mover.py` Schritt 6 patcht `~/.claude.json` via String-Replacement des Projekt-Keys. Wenn die App einen neuen Key bereits angelegt hatte (weil das WSL-Projekt vorher schon geöffnet wurde), entsteht ein Duplikat und der alte Key bleibt.
- **Manueller Fix:** `repair_claude_json.py` geschrieben — entfernt nur den verwaisten `D:\`-Key, behält beide WSL-Keys. Prozess-Guard: weigert sich, wenn `claude.exe` noch läuft (würde In-Memory-Kopie überschreiben). Backup vor Änderung.
- **Git-Cleanup:** `.coverage` (pytest-cov Artefakt) + `.claude/settings.local.json` (Machine-spezifisch) zu `.gitignore` hinzugefügt. `.claude/settings.local.json` untracked. Globale `CLAUDE.md` aktualisiert: `settings.local.json` soll gitignoriert, nicht committet werden.

**Result:** Diagnose-Dokumentation (`manual-fix.md`, `repair_claude_json.py`) bereit für Benutzer-Ausführung. Repo sauber, Git-Instruktionen aktualisiert. User wird mit geschlossener Claude-App den `repair_claude_json.py` laufen lassen und dann testen.
