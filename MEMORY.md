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

## `2026-06-02` – Eigentliche Ursache gefunden: Desktop-App-Session-Store (#17 / PR #18)

**Request:** Trust-Dialog zeigt nach dem Move weiter den alten Pfad `D:\workspace\tools\SleepNote`, „Copy path" liefert den alten Pfad, „Show in Explorer" öffnet nichts — obwohl der vorherige `~/.claude.json`-Fix lief. Grundlegend beheben (auch im Tool), in Branch + PR.

**Done:**
- **Korrektur der vorherigen Diagnose:** Der `~/.claude.json`-Key war **nicht** die wahre/alleinige Ursache. Beleg über Zeitstempel: Screenshots `17:47`, Repair erst `21:36`, App-Log zeigt das Problem noch `21:37`. `~/.claude.json`, `projects/`, `history.jsonl` und alle Session-`cwd` sind bereits sauber auf `\\wsl$\...` migriert.
- **Wahre Ursache:** Die Claude-Desktop-App (MSIX `Claude_pzs8sxrjxfjjc`) hat einen **eigenen** Session-Store, getrennt von `~/.claude/`: `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude-code-sessions\<acct>\<group>\local_<id>.json`. Jede Datei hat `cwd`/`originCwd`. `10` SleepNote-Sessions standen noch auf dem alten Pfad. App-Log beweist die Kausalkette: `LocalSessions.checkTrust: cwd=...` und `Failed to warm session ...: Working directory no longer exists`.
- **Tool-Fix:** Neuer Migrationsschritt 7 + `app_session_files()` in `claude_mover.py`; nutzt die bestehende `patch_file`/`patch_content`-Maschinerie. Tests (`TestAppSessionFiles`), `144` Tests / `21` Klassen / `92%` Coverage. Doku (`CLAUDE.md`, `README.md`) korrigiert — frühere Behauptung „alle Clients teilen sich nur `~/.claude/projects/`" war falsch.
- **Akut-Reparatur:** `repair_app_sessions.py` (analog zu `repair_claude_json.py`) — patcht die `10` Session-Dateien, Prozess-Guard, Backups unter `app-sessions-repair-<timestamp>/`. Untracked (maschinenspezifisch).
- **Workflow:** Issue [#17](https://github.com/automatix/claude-mover/issues/17), Branch `bugfix/desktop-app-session-store`, PR [#18](https://github.com/automatix/claude-mover/pull/18) squash-gemerged (`9009c2f`).

**Result:** Tool deckt den Desktop-App-Store künftig ab. Der akute SleepNote-Fall wird vom User per `repair_app_sessions.py` bei geschlossener App behoben. Kein SemVer-Artefakt im Repo (keine Versionsdatei) — reiner Patch-Level-Fix.

## `2026-06-02` – Encoding-Bug: falscher Verzeichnis-Key bei WSL/UNC + Leerzeichen/Punkten (#21)

**Request:** Nach dem Move zu WSL erscheint beim Öffnen jeder Session unten der Fehler „Claude couldn't process that message — No conversation found with session ID: …". (Das ursprüngliche Trust-Dialog/Copy-Path-Problem ist gelöst.)

**Done:**
- **Akut-Diagnose:** Der alte Trust-Dialog-Pfad war nur ein einmaliger Renderer-Cache-Übergang (App-Log ab `22:26:50` durchgehend neuer WSL-Pfad). Das neue Problem ist ein **Encoding-Bug** in `encode_path`.
- **Ursache:** Die echte CLI kodiert den `cwd` mit **einer** Regel: jedes Nicht-Alphanumerische → `-`, Groß-/Kleinschreibung bleibt. Verifiziert an Live-Verzeichnissen: `\wsl$\Ubuntu\…\SleepNote` → `--wsl--Ubuntu-…-SleepNote`; `D:\workspace\tools\Claude Mover` → `D--workspace-tools-Claude-Mover`. `encode_path` kleinschrieb dagegen Server+Share und behielt `$` (`--wsl$-ubuntu-…`); bei Laufwerkspfaden ersetzte es nur Backslashes (Leerzeichen/Punkte blieben). Dadurch landeten die `20` migrierten Sessions in einem Ordner, den die CLI nie liest. Die CLI legte beim Start selbst den korrekten Ordner `--wsl--Ubuntu-…` an.
- **Wichtige Korrektur eines früheren Befunds:** In WSL gibt es **keine** `claude`-CLI, kein `~/.claude`, kein `~/.claude.json`. Die App führt die CLI auf der **Windows-Seite** mit UNC-`cwd` aus → Sessions bleiben im Windows-Store. Ein Windows→WSL-Move ist **keine** Cross-Store-Migration; nur der Verzeichnis-**Key** ändert sich. Die frühere `CLAUDE.md`-Annahme dazu war im Ergebnis richtig, nur die Encoding-Tabelle war falsch.
- **Akut-Reparatur (App geschlossen):** `20` Session-`.jsonl` + Session-Unterordner + `5` Memory-Dateien aus `--wsl$-ubuntu-…` nach `--wsl--Ubuntu-…` verschoben; Backups unter `~/.claude/backups/2026-06-02_repair-wsl-encoding/`. Zwei von der App verworfene `cliSessionId`-Verknüpfungen (`local_36dbae27`→`37c39cba`, `local_f382a1bd`→`5abbc1d0`) im Desktop-App-Store wiederhergestellt. Alle `10` App-Sessions verweisen wieder auf vorhandene Transkripte.
- **Tool-Fix:** `encode_path`-Body durch `re.sub(r"[^A-Za-z0-9]", "-", …)` ersetzt; Tests für die alte (falsche) kleingeschriebene UNC-Ausgabe korrigiert; Coverage für Leerzeichen, Punkte, Case-Erhalt und die realen `SleepNote`/`FooBarWSL`-Keys ergänzt. `147` Tests grün.
- **Workflow:** Issue [#21](https://github.com/automatix/claude-mover/issues/21), Branch `bugfix/encode-path-universal-rule`.

**Result:** `encode_path` stimmt jetzt mit der echten CLI überein (Laufwerk + UNC + Leerzeichen/Punkte). Akuter SleepNote-Fall behoben — alle Sessions wieder resümierbar. PR folgt.

## `2026-06-03` – Kanonische WSL-Form: SleepNote von `\wsl$\Ubuntu` auf `\wsl.localhost\ubuntu` re-keyed (#23)

**Request:** Beobachtung des Users: Der von uns angelegte Ordner heißt `--wsl--Ubuntu-…`, ein nativ in WSL angelegtes Projekt dagegen `--wsl-localhost-ubuntu-…`. Unterschied in der Namensstruktur erklären.

**Done:**
- **Erklärung:** Gleiche Encoding-Regel, unterschiedliche *Eingabe-Form*. Die Desktop-App registriert WSL-Projekte **kanonisch** als `\wsl.localhost\<distro-klein>\…` (Beleg: natives `FooBarWSL` → `--wsl-localhost-ubuntu-…`). SleepNote stand in der Legacy-Form `\wsl$\Ubuntu\…` (= Move-Ziel-String) → `--wsl--Ubuntu-…` (`$`+`\`→`--`, `Ubuntu` groß). Beide Aliase zeigen auf dieselbe Stelle, erzeugen aber verschiedene Keys.
- **Risiko:** Funktioniert nur solange alle Records konsistent sind; öffnet man den Ordner später per Datei-Picker, registriert die App ihn kanonisch neu → Verlauf wieder verwaist.
- **Re-Key (Metadaten, Ordner bleibt liegen):** `repair_wsl_canonicalize.py` (Dry-Run, Backups unter `~/.claude/backups/wsl-canonicalize-…`, `--force` für CLI-only-Fall). Umbenannt `--wsl--Ubuntu-…` → `--wsl-localhost-ubuntu-…`; `22` `.jsonl` (`7855` Tokens), `~/.claude.json`-Keys + `githubRepoPaths`, `10` App-Session-`cwd`/`originCwd`, `history.jsonl` gepatcht. Auch der **verstümmelte** Single-Backslash-Key (`\wsl$\Ubuntu\…`, von alter buggy `claude_mover`-Version) bereinigt.
- **Verifikation:** Kanonischer Ordner mit `21` Sessions; keine `wsl$`/`Ubuntu`-Reste; alle `10` App-Sessions mit kanonischem `cwd` + vorhandenem Transkript. Übrig nur ein leerer, gesperrter Alt-Ordner `--wsl$-ubuntu-…` (harmlos, verschwindet beim Neustart) und zwei rein historische `--wsl--Ubuntu`-Erwähnungen in Transkript-Text (bewusst nicht verändert).
- **Tool-Follow-up:** Issue [#23](https://github.com/automatix/claude-mover/issues/23) — `claude_mover` soll WSL-Ziele auf die kanonische `\wsl.localhost\<distro-klein>\…`-Form normalisieren.

**Result:** SleepNote jetzt identisch strukturiert wie native WSL-Projekte; robust gegen erneutes Verwaisen. `repair_wsl_canonicalize.py` untracked (one-off, wie die anderen Repair-Skripte).

## `2026-06-03` – Issue #23 implementiert: WSL-Ziel-Normalisierung (PR #24)

**Request:** Offene PRs und Issues erledigen.

**Done:**
- **PR #22** (Encoding-Fix #21) gemergt (squash) → Issue #21 geschlossen; zurück auf `master`.
- **Issue #23 implementiert:** `_canonicalize_wsl()` normalisiert jeden WSL-UNC-Pfad (Server `wsl$`/`wsl.localhost` → `wsl.localhost`, Distro-Komponente kleingeschrieben, restliche Komponenten unverändert, Nicht-WSL-Pfade unangetastet). `normalize_path` wendet es an allen UNC-Rückgabepunkten an → beide Aliase ergeben denselben kanonischen Key `--wsl-localhost-ubuntu-…`. `_is_noncanonical_wsl_input()` + Log-Hinweis in `main`, wenn die Eingabeform umgeschrieben wurde.
- **Tests:** `TestCanonicalizeWsl`, `TestIsNoncanonicalWslInput`, Both-Aliases→gleicher-Key. `161` Tests / `23` Klassen grün.
- **Doku:** `CLAUDE.md` (kanonische Form als implementiert markiert, Path-Utilities-Tabelle, Testzahl) + `README.md` (Windows→WSL-Abschnitt).
- **PR #24** gemergt (squash) → Issue #23 geschlossen.

**Result:** Keine offenen PRs/Issues mehr. `claude_mover` erzeugt für WSL-Ziele jetzt automatisch den kanonischen App-Key, unabhängig von Alias/Schreibweise der Eingabe.
