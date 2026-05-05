# Konversation: Claude Code – Projektordner verschieben

---

## Frage: Claude Cowork / Claude Code – Was soll beachtet werden, wenn der Ordner eines Projekts verschoben wird?

Claude Cowork / Claude Code: Was soll beachtet werden, wenn der Ordner eines Claude Cowork / Claude Code Projekts verschoben wird? Wie soll das am besten gemacht werden, um Verwirrungen zu vermeiden.

---

## Antwort

Das ist eine wichtige Frage, denn das einfache Verschieben eines Projektordners kann dazu führen, dass der gesamte Gesprächsverlauf mit Claude Code „verschwindet". Hier ist alles, was du wissen musst:

---

### Das Kernproblem

Claude Code speichert alle Gesprächsdaten (Sessions, Verlauf, Entscheidungen) unter `~/.claude/projects/` – und zwar mit dem **absoluten Pfad** des Projektordners als Schlüssel. Wenn du den Ordner einfach umbenennst oder verschiebst, werden diese Daten nicht automatisch mitbewegt. Sie sind dann nicht gelöscht, sondern „verwaist" – erreichbar über den alten Pfad, der nun nicht mehr existiert.

---

### Was intern passiert

Claude Code kodiert Verzeichnispfade, indem Schrägstriche durch Bindestriche ersetzt werden. Ein Projekt unter `/home/user/projects/myapp` wird z. B. als `-home-user-projects-myapp` im Ordner `~/.claude/projects/` gespeichert. Jede Session liegt dort als `.jsonl`-Datei.

Zusätzlich gibt es im Projektordner selbst:

- `.claude/` – projektspezifische Einstellungen, Befehle, Hooks
- `CLAUDE.md` – der Projektkontext/Instruktionen
- `.mcp.json` – MCP-Server-Konfiguration

---

### Die richtige Vorgehensweise beim Verschieben

Die Reihenfolge ist kritisch: Der Claude-Kontext muss **vor** dem Verschieben des Ordners umgezogen werden, nicht danach. Wer zuerst den Ordner verschiebt, versucht danach Kontext von einem Pfad zu migrieren, der nicht mehr existiert.

**Schritt-für-Schritt manuell:**

1. **Zuerst** den Claude-Projektordner in `~/.claude/projects/` umbenennen:
   ```bash
   cd ~/.claude/projects/
   mv -- -alter-pfad-encoded -neuer-pfad-encoded
   ```

2. **Dann** den eigentlichen Projektordner verschieben/umbenennen.

3. Absolute Pfade in Konfigurationsdateien aktualisieren:
   ```bash
   sed -i 's|/alter/pfad|/neuer/pfad|g' .claude/settings.json
   sed -i 's|/alter/pfad|/neuer/pfad|g' .mcp.json
   ```

4. Außerdem sollte `~/.claude/history.jsonl` aktualisiert werden, da dort ebenfalls Pfadangaben gespeichert sind.

---

### Einfachere Lösung: `claude-mv` Script

Es gibt ein Community-Script namens `claude-mv`, das den gesamten Prozess automatisiert: Es verschiebt zuerst den Claude-Kontext, schreibt dann Pfadreferenzen in den `.jsonl`-Dateien um, verschiebt danach erst den Projektordner, und aktualisiert schließlich den History-Index. Das Script unterstützt auch einen **Merge-Modus**, falls an zwei Orten an verwandten Projekten gearbeitet wurde.

Installation:

```bash
mkdir -p ~/dotfiles/scripts
curl -o ~/dotfiles/scripts/claude-mv \
  https://raw.githubusercontent.com/curiouslychase/dotfiles/main/scripts/claude-mv
chmod +x ~/dotfiles/scripts/claude-mv
# Pfad zur PATH hinzufügen, dann:
claude-mv /alter/pfad /neuer/pfad
```

---

### Projektinterne Dateien (`.claude/`, `CLAUDE.md`)

Diese Dateien liegen **im Projektordner selbst** und werden beim Verschieben automatisch mitgenommen – kein Problem. Sie können auch ins Git-Repository eingecheckt werden, damit das ganze Team dieselbe Konfiguration nutzt.

---

### Kurzfassung

| Was | Problem beim einfachen Verschieben |
|---|---|
| Gesprächsverlauf / Sessions | ❌ Gehen verloren (verwaist in `~/.claude/projects/`) |
| `.claude/`-Ordner im Projekt | ✅ Wird mitgenommen |
| `CLAUDE.md` | ✅ Wird mitgenommen |
| `.mcp.json` mit absoluten Pfaden | ⚠️ Muss manuell angepasst werden |

**Faustregel:** Immer `claude-mv` oder die manuelle Methode (erst Kontext, dann Ordner) verwenden – nie einfach in Finder/Explorer umbenennen ohne Vorbereitung.

---

## Anfrage: Konversation als MD-File exportieren

Packe unsere gesamte Konversation oben in ein MD-File. Betitele meine Prompts und Deine Antworten unreserviere bzw. verwende für sie `H2` bzw. `##`.

---

## Antwort

*(Diese Datei ist das Ergebnis dieser Anfrage.)*
