---
name: hsd-update
description: Read and update HSD (Hardware Sighting Database) articles via the HSD REST API with Kerberos/SSPI authentication. Use when the user asks to read, view, get, update, modify, or close HSD articles, sightings, or hardware sighting database entries.test
---

# HSD Update Skill

Read and update HSD sighting articles using Kerberos/SSPI authentication (Windows Integrated Auth — automatic, no password).

## Prerequisites

Install from the requirements file bundled with this skill:

```bash
pip install -r ~/.copilot/skills/hsd-update/requirements.txt
```

- **Windows** with Intel domain credentials (logged in)
- **Intel VPN** connection
- **Python 3.7+**

## Quick Start

The client script is at `~/.copilot/skills/hsd-update/hsd_client.py`.

**Read an article (all fields):**
```bash
python ~/.copilot/skills/hsd-update/hsd_client.py get --sighting-id "1306793693" --no-verify-ssl
```

**Query articles by title:**
```bash
python ~/.copilot/skills/hsd-update/hsd_client.py query --title "geni" --no-verify-ssl
```

**Read specific fields:**
```bash
python ~/.copilot/skills/hsd-update/hsd_client.py get --sighting-id "1306793693" --fields "id,title,status,priority,owner,description" --no-verify-ssl
```

**Update an article:**
```bash
python ~/.copilot/skills/hsd-update/hsd_client.py update --sighting-id "1306793693" --tenant "sighting_central" --subject "sighting" --set description="Updated via skill" --no-verify-ssl
```

## Authentication

Uses **Kerberos/SSPI** via `requests-negotiate-sspi` — transparently sends the user's Windows domain Kerberos ticket. No passwords, tokens, or device codes needed.

Falls back to **NTLM** (with password prompt) if `requests-negotiate-sspi` is unavailable.

Verify your Kerberos ticket with `klist`.

## API Details

| Property | Value |
|----------|-------|
| **Base URL** | `https://hsdes-api.intel.com` |
| **GET article endpoint** | `/rest/article/{sighting_id}` |
| **GET query endpoint** | `/rest/query?title={title}` |
| **PUT endpoint** | `/rest/article/{sighting_id}` |
| **Auth** | Kerberos/SSPI (Windows Integrated Auth) |

## Update Field Input Methods

| Method | Best for | Example |
|--------|----------|---------|
| `--set KEY=VALUE` | PowerShell, single fields | `--set status=closed --set priority=high` |
| `--fields '{"k":"v"}'` | Bash/Linux, JSON string | `--fields '{"status": "closed"}'` |
| `--fields-file path.json` | Any shell, complex payloads | `--fields-file /tmp/fields.json` |

**PowerShell note**: `--fields` with raw JSON does not work in PowerShell due to quote mangling. Use `--set key=value` (repeatable) or `--fields-file` instead.

## Required Information

### For Reading (GET article)
1. **Sighting ID** — the HSD article identifier (e.g., `1306793693`)

### For Querying by Title (GET query)
1. **Title** — a search string to match against article titles (e.g., `geni`)

### For Updating (PUT)
1. **Sighting ID** — the HSD article identifier
2. **Tenant** — e.g., `sighting_central`, `server`, `client`
3. **Subject** — e.g., `sighting`
4. **Field Values** — key-value pairs to update

**Tip:** If you don't know the tenant, subject, or valid field values, GET the article first and inspect its current values.

## Common HSD Fields

| Field | Description |
|-------|-------------|
| `status` | Article status (`open`, `closed`, `in_progress`) |
| `priority` | Priority level (`low`, `medium`, `high`, `critical`) |
| `severity` | Bug severity |
| `owner` | Article owner email |
| `assigned_to` | Assigned person |
| `component` | Hardware component affected |
| `found_in_build` | Build where issue was found |
| `fixed_in_build` | Build with fix |
| `root_cause` | Root cause description |
| `resolution` | Resolution status |
| `comment` | Add a comment/note |
| `description` | Article description |
| `title` | Article title |

**Important:** Field values returned from GET reveal the exact lookup values the API accepts (e.g., `"4-low"`, `"3-medium"`). Use these exact formats when updating.

## Workflows

### Read an Article
```
User: "Show me HSD sighting 1306793693"
1. Run: python ~/.copilot/skills/hsd-update/hsd_client.py get --sighting-id "1306793693" --no-verify-ssl
2. Parse the JSON response
3. Present key fields: title, status, priority, owner, description
```

### Query Articles by Title
```
User: "Find HSD articles with title containing 'geni'"
1. Run: python ~/.copilot/skills/hsd-update/hsd_client.py query --title "geni" --no-verify-ssl
2. Parse the JSON response (returns a list of matching articles)
3. Present each article: id, title, status, priority, owner
```

### Read Specific Fields
```
User: "What's the status of HSD 1306793693?"
1. Run: python ~/.copilot/skills/hsd-update/hsd_client.py get --sighting-id "1306793693" --fields "id,title,status,priority" --no-verify-ssl
2. Present the requested fields
```

### Read Before Update (Discover Valid Values)
```
User: "Change the priority of HSD 1306793693 to medium"
1. GET the article first to discover current priority format (e.g., "4-low")
2. Infer the correct lookup value (e.g., "3-medium")
3. Execute the update with the correct value
```

### Update Fields
```
User: "Update HSD 1306793693 priority to critical"
1. Gather tenant and subject (GET first if unknown)
2. Run: python ~/.copilot/skills/hsd-update/hsd_client.py update --sighting-id "1306793693" --tenant "sighting_central" --subject "sighting" --set priority=critical --no-verify-ssl
3. Confirm the update
```

### Close an Article
```
User: "Close HSD 1306793693"
1. Run: python ~/.copilot/skills/hsd-update/hsd_client.py update --sighting-id "1306793693" --tenant "sighting_central" --subject "sighting" --set status=closed --no-verify-ssl
2. Confirm closure
```

## Presenting Results

### After GET:
```
HSD Article 1306793693

- Title: [title]
- Status: [status]
- Priority: [priority]
- Owner: [owner]
- Description: [description]

Article URL: https://hsdes-api.intel.com/article/1306793693
```

### After Update:
```
Successfully updated HSD article 1306793693

Updated fields:
- status: closed
- priority: high

Article URL: https://hsdes-api.intel.com/article/1306793693
```

## Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| **401 Unauthorized** | Kerberos ticket expired/invalid | Run `klist` to check; log out/in to refresh |
| **403 Forbidden** | No permission to modify article | Verify HSD roles/permissions |
| **404 Not Found** | Sighting ID doesn't exist | Check the ID |
| **400 Bad Request** | Invalid field names/values | GET article first to discover valid values |
| **ImportError** | Missing `requests-negotiate-sspi` | `pip install -r ~/.copilot/skills/hsd-update/requirements.txt` |
| **Connection timeout** | Not on Intel network | Connect to VPN |

## Request Body Structure (PUT)

```json
{
  "tenant": "string",
  "subject": "string",
  "fieldValues": [
    { "fieldName": "fieldValue" }
  ]
}
```
