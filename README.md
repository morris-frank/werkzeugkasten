# Werkzeugkasten

## Functions

### 1. Summarize

Availability: MenuBar, Finder extension
Input: File, Files, Text
Output: Markdown _and_ `###.summary.md` sidecar file

### 2. Research list

Availability: MenuBar
Input: List[Markdown] + Question[Text]
Output: List[Markdown]

### 3. Research table

Availability: MenuBar
Input: File[CSV]/File[Markdown] or Text[CSV]/Text[Markdown]
Output: Table[Markdown]

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