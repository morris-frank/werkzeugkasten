# Werkzeugkasten

Werkzeugkasten is a macOS menu-bar app with a Finder action for lightweight research, summarization, and Codex log cleanup tasks.

## Functions

### 1. Summarize

| :inbox_tray: **Input** | :outbox_tray: **Output** | :mag: **Where** |
| --- | --- | --- |
| File(s)<br>Text | Markdown (creates `###.summary.md` sidecar) | MenuBar<br>FinderExtension |

### 2. Research List

| :inbox_tray: **Input** | :outbox_tray: **Output** | :mag: **Where** |
| --- | --- | --- |
| List + a question | Markdown: answers + derivative research table | MenuBar |

### 3. Research Table

| :inbox_tray: **Input** | :outbox_tray: **Output** | :mag: **Where** |
| --- | --- | --- |
| CSV<br>Markdown | Markdown: imputed table + derivative columns | MenuBar |

:jigsaw: **Options:**

- `include_sources`
   Include the URLS of the web sources in a new column `"Sources"`
- `include_source_raw`
   Include the _content_ of the web sources in a new column `"Sources[RAW]"`
- `auto_tagging`
   Use the filled table to infer sensible categories, new column `"Tags"`
- `nearest_neighbour`
   Use the filled table to find closest subjects, new column `"Closest $OBJECT_TYPE"`

### 4. Prettify Codex Log

| :inbox_tray: **Input** | :outbox_tray: **Output** | :mag: **Where** |
| --- | --- | --- |
| Codex `.jsonl` log | `<name>.jsonl.transcript.md` written next to the input log | MenuBar |

# Installation

1. Download the most recent release [Werkzeugkasten.zip](https://github.com/morris-frank/werkzeugkasten/releases)
2. Install and/or start
3. Open `Settings` from the menu bar:
   - :key: OpenAI API key
   - :key: [Jina API Key](https://jina.ai/)
   - Python interpreter path, (`type python`)
   - Optional(default: `gpt-5`): research model and summary model
4. If Finder does not show the extension immediately, enable it in:
   - System Settings > Privacy & Security > Extensions

## Example table research

**Request**

| Movie | Release Year | Country | theme | What is the most general theme of the movie? |
| --- | --- | --- | --- | --- |
| where is my friend's house? |  | Iran |  |  |
| The Life and Death of Colonel Blimp | 1943 |  |  |  |
| Possession |  |  |  |  |

**Response**

| **Movie** | **Release Year** | **Country** | **theme** | **What is the most general theme of the movie?** |
| --- | --- | --- | --- | --- |
| where is my friend’s house? | 1987 | Iran | friendship | Its most general theme is friendship and moral responsibility. |
| The Life and Death of Colonel Blimp | 1943 | UK | honor | Its most general theme is the endurance and evolution of honor and friendship across war and time. |
| Possession | 1981 | France/West Germany | divorce | The movie’s most general theme is marital breakdown and separation. |
