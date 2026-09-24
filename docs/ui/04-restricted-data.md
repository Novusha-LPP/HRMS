# UI 4 · Restricted data on screen

The access model decides what reaches the browser (Architecture 5). The UI's job is to make restrictions visible and understandable, and to never leak through side channels.

| Data class | In lists and tables | In Employee 360 | In history | In notifications, search and exports |
|---|---|---|---|---|
| Directory | Shown | Shown | Shown | Allowed |
| Personal | Hidden unless the role grants it | Shown to granted roles | Shown to granted roles | Email and in-app only; never SMS or WhatsApp |
| Financial | **Never a column** | SensitiveField: masked, reveal logged | Field name plus "Restricted" to others | Never in message bodies; exports only for granted roles, logged |
| Identity | **Never a column** | SensitiveField: masked, reveal logged | Field name plus "Restricted" to others | Never in message bodies; not indexed for search |
| Case | Absent | Section **absent** for users without access (not a lock) | Absent | Never |

Rules:

- **Masked by default, even for people who may see the value.** Reveal is a deliberate click, and each reveal writes to the sensitive-read log (SensitiveField).
- **Explain, don't hide, for Financial and Identity.** A user without access sees the `.hr-restricted` placeholder with the class name, so they know it exists and whom to ask.
- **Hide entirely for Case data.** The existence of a grievance or disciplinary record can itself be sensitive.
- **Employee self-service** shows the employee their own values; they may request a correction but not edit protected fields (§25).
- **Screenshots and printing:** exports and printed letters with Financial or Identity data carry the viewer's name and time as a watermark where the tenant enables it.
