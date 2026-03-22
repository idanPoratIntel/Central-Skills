---
name: my-teams-messages
description: Retrieve your own Microsoft Teams messages from chats and channels using Graph Search API with MSAL device-code authentication. Use when the user asks to read, search, or list their Teams messages, find chats by topic or member, or check their Teams conversations.
---

# My Teams Messages Skill

Retrieve **only the signed-in user's own messages** across all Teams chats and channels using the Microsoft Graph Search API.

## Prerequisites

Install from the requirements file bundled with this skill:

```bash
pip install -r ~/.copilot/skills/my-teams-messages/requirements.txt
```

## Authentication

| Property | Value |
|----------|-------|
| **Method** | MSAL device-code flow |
| **Client ID** | `14d82eec-204b-4c2f-b7e8-296a70dab67e` (Microsoft Graph CLI Tools — pre-consented, no admin consent) |
| **Scopes** | `User.Read`, `Chat.Read` (user-consent only) |
| **Token cache** | `~/.msal_my_messages_cache.bin` (auto-refreshed) |

On first use the user will see a device-code prompt on stderr. After that, tokens refresh silently.

## Client Script

```
python ~/.copilot/skills/my-teams-messages/my_teams_messages.py <ACTION> [OPTIONS]
```

All stderr output is diagnostic. Stdout is always JSON (or pretty text with `--pretty`).

## Available Actions

| Flag | Description |
|------|-------------|
| `--my-messages` | Retrieve your own messages from chats and channels |
| `--me` | Show the signed-in user profile |
| `--chats` | List your recent chats (with members) |
| `--chat-messages CHAT_ID` | Read messages from a specific chat by ID |
| `--find-chat TOPIC` | Find a group chat by topic name and return its messages |
| `--find-member NAME` | Find a chat by member display name (1:1 first, then group) |

### Filtering & Output Options

| Flag | Description |
|------|-------------|
| `--keyword TEXT` | Filter messages by keyword |
| `--top N` | Number of messages to return (default 25) |
| `--pretty` | Human-readable output |
| `--clear-cache` | Delete cached tokens and exit |

## Usage Patterns

### Your Recent Messages
```bash
python ~/.copilot/skills/my-teams-messages/my_teams_messages.py --my-messages --top 10 --pretty
```

### Search Messages by Keyword
```bash
python ~/.copilot/skills/my-teams-messages/my_teams_messages.py --my-messages --keyword "deployment" --top 10 --pretty
```

### Messages with a Person (1:1 chat by member name)
```bash
python ~/.copilot/skills/my-teams-messages/my_teams_messages.py --find-member "Doe, John" --top 10 --pretty
```

### Messages from a Group Chat (by topic)
```bash
python ~/.copilot/skills/my-teams-messages/my_teams_messages.py --find-chat "Project Alpha" --top 10 --pretty
```

### List Your Chats
```bash
python ~/.copilot/skills/my-teams-messages/my_teams_messages.py --chats --top 20
```

### Read a Known Chat by ID
```bash
python ~/.copilot/skills/my-teams-messages/my_teams_messages.py --chat-messages "19:abc...@thread.v2" --top 10 --pretty
```

### Verify Identity
```bash
python ~/.copilot/skills/my-teams-messages/my_teams_messages.py --me
```

### Re-authenticate
```bash
python ~/.copilot/skills/my-teams-messages/my_teams_messages.py --clear-cache
python ~/.copilot/skills/my-teams-messages/my_teams_messages.py --my-messages --top 5 --pretty
```

## How It Works

Uses the **Microsoft Graph Search API** (`POST /search/query`) with `entityTypes: ["chatMessage"]`. Since the KQL `from:me` operator does not work for chat messages, the script:

1. Calls `/me` to get your email address
2. Fetches messages from the Search API (with optional keyword filter)
3. Client-side filters results to only include messages where `from.emailAddress.address` matches your email
4. Automatically paginates to collect enough matching results

## Response Structure

### JSON Envelope (default)

```json
{
  "success": true,
  "status": 200,
  "data": {
    "total": 5,
    "hits": [
      {
        "hitId": "...",
        "summary": "snippet...",
        "resource": {
          "createdDateTime": "2026-02-20T10:30:00Z",
          "from": { "user": { "displayName": "Your Name" } },
          "body": { "content": "Full message text..." },
          "chatId": "19:abc...@thread.v2"
        }
      }
    ]
  }
}
```

### Pretty Output

```
Found 5 message(s) from you:
──────────────────────────────────────────────────

[2026-02-20T10:30:00Z] Your Name:
  Full message text...
  [Chat] 19:abc123...
```

## Error Handling

| Code | Meaning | Action |
|------|---------|--------|
| **200** | OK | — |
| **401** | Token expired | Auto-retried once; if persists, suggest `--clear-cache` |
| **403** | Missing permissions | Suggest `--clear-cache` and re-authenticate |
| **429** | Throttled | Wait and retry after `Retry-After` delay |

## Best Practices

1. **Start with `--me`** to verify authentication works before querying messages.
2. **Use `--top`** to keep payloads small — default is 25.
3. **Use `--keyword`** to narrow results when looking for specific conversations.
4. **Use `--pretty`** for human-readable output in terminal.
5. **Clear cache to re-auth** — `--clear-cache` then re-run if tokens fail.
