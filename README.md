# Werkzeugkasten

Werkzeugkasten is a macOS menu-bar app with a Finder action for lightweight research, summarization, and Codex log cleanup tasks.

## Functions

### 1. Summarize

Availability: Menu bar, Finder action
Input: File, files, text
Output: Markdown and `###.summary.md` sidecar files

### 2. Research List

Availability: Menu bar
Input: Markdown list plus a question
Output: Markdown list with completed research

### 3. Research Table

Availability: Menu bar
Input: CSV or Markdown table from a file or pasted text
Output: Markdown table

### 4. Prettify Codex Log

Availability: Menu bar
Input: Codex session `.jsonl` log
Output: `<name>.jsonl.transcript.md` written next to the input log

## Local setup

Werkzeugkasten uses an external Python interpreter in v1. Install Python first, then point the app at that interpreter in Settings.

1. Install Python 3.11 or newer.
2. Install the Python dependencies:
   - `python3 -m pip install -r requirements.txt`
3. Regenerate the Xcode project:
   - `xcodegen generate`
4. Open `Werkzeugkasten.xcodeproj` in Xcode and run the `Werkzeugkasten` scheme.

## First run

1. Open `Settings` from the menu bar.
2. Set:
   - OpenAI API key
   - research model
   - summary model
   - Python interpreter path
3. Save the settings.
4. If Finder does not show the extension immediately, enable it in:
   - System Settings > Privacy & Security > Extensions

Saved settings are shared with the Finder action through the configured App Group and Keychain Sharing entitlements.

## Finder action

The Finder integration is a no-UI macOS Action extension. It reads the shared settings saved by the app and posts a notification when the summarize run completes or fails.

If it does not appear:

1. Confirm the app has been launched at least once.
2. Save settings successfully in the app.
3. Enable the extension in System Settings.
4. Check Signing & Capabilities in Xcode for the App Group and Keychain Sharing configuration.

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

## Releasing

The GitHub release flow builds a signed and notarized macOS app zip.

- Release checklist: [`docs/releasing.md`](docs/releasing.md)
- GitHub Actions workflow: [`.github/workflows/release.yml`](.github/workflows/release.yml)
