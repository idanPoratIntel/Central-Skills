#!/usr/bin/env python3
"""
Retrieve only YOUR OWN Microsoft Teams messages (chats + channels).
Uses the Microsoft Graph Search API with KQL `from:me` to server-side
filter messages authored by the signed-in user.

Authentication: MSAL device-code flow with the Microsoft Graph CLI Tools
first-party app (pre-consented in most enterprise tenants — no admin
consent required).

Usage:
    python .github/skills/my_teams_messages.py --my-messages
    python .github/skills/my_teams_messages.py --my-messages --keyword "deployment"
    python .github/skills/my_teams_messages.py --my-messages --top 10 --pretty
    python .github/skills/my_teams_messages.py --chats --top 20
    python .github/skills/my_teams_messages.py --chat-messages <CHAT_ID> --top 10 --pretty
    python .github/skills/my_teams_messages.py --clear-cache
"""

import argparse
import json
import os
import sys
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

import msal
import requests

# ── Configuration ─────────────────────────────────────────────────
# Microsoft Graph Command Line Tools — a Microsoft first-party app
# that is pre-consented in most enterprise Azure AD tenants.
# This avoids the admin-consent wall that custom app registrations hit.
CLIENT_ID = os.environ.get("GRAPH_CLIENT_ID", "14d82eec-204b-4c2f-b7e8-296a70dab67e")
AUTHORITY = os.environ.get(
    "GRAPH_AUTHORITY",
    "https://login.microsoftonline.com/46c98d88-e344-4ed4-8496-4ed7712e255d/",
)
# Only user-consent scopes — no admin consent required
SCOPES = [
    "User.Read",
    "Chat.Read",
]
TOKEN_CACHE = os.path.join(os.path.expanduser("~"), ".msal_my_messages_cache.bin")
GRAPH = "https://graph.microsoft.com/v1.0"


# ── HTML Stripping ────────────────────────────────────────────────

class _HTMLStripper(HTMLParser):
    """Minimal HTML-to-text converter for Teams messages."""

    def __init__(self):
        super().__init__()
        self._parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "emoji":
            self._parts.append(attrs_d.get("alt", ""))

    def handle_endtag(self, tag):
        if tag in ("p", "div", "br"):
            self._parts.append("\n")

    def handle_data(self, data):
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts).strip()


def strip_html(html: str) -> str:
    if not html:
        return ""
    s = _HTMLStripper()
    s.feed(html)
    return s.text()


# ── Token Cache ───────────────────────────────────────────────────

def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE):
        with open(TOKEN_CACHE, "r") as f:
            cache.deserialize(f.read())
    return cache


def _save_cache(cache: msal.SerializableTokenCache):
    if cache.has_state_changed:
        with open(TOKEN_CACHE, "w") as f:
            f.write(cache.serialize())


# ── Authentication (device-code only) ────────────────────────────

def get_token() -> str:
    """Acquire a Graph API access token.

    1. Try the cached/refreshed token silently.
    2. Fall back to device-code flow (print a URL + code to stderr).
    """
    cache = _load_cache()
    app = msal.PublicClientApplication(
        CLIENT_ID, authority=AUTHORITY, token_cache=cache
    )

    # 1. Silent / refresh
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save_cache(cache)
            _log("Using cached token")
            return result["access_token"]

    # 2. Device-code flow
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        _die(f"Device flow failed: {flow.get('error_description', flow)}")

    _log("=" * 60)
    _log("SIGN IN  —  Microsoft Graph (My Messages)")
    _log("=" * 60)
    _log(flow["message"])
    _log("=" * 60)

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" in result:
        _save_cache(cache)
        _log("Authentication successful!")
        return result["access_token"]

    _die(f"Auth failed: {result.get('error_description', result.get('error'))}")


# ── HTTP Helper ───────────────────────────────────────────────────

_token: Optional[str] = None


def _headers() -> Dict[str, str]:
    global _token
    if _token is None:
        _token = get_token()
    return {
        "Authorization": f"Bearer {_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def graph(
    endpoint: str,
    method: str = "GET",
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Call a Microsoft Graph REST endpoint. Returns parsed JSON envelope."""
    global _token
    url = endpoint if endpoint.startswith("http") else f"{GRAPH}{endpoint}"
    _log(f"{method} {url}")

    resp = requests.request(
        method, url, headers=_headers(), params=params, json=body, timeout=30
    )

    # Auto-retry once on 401 (token expired)
    if resp.status_code == 401:
        _log("Token expired — refreshing…")
        _token = None  # force re-auth
        resp = requests.request(
            method, url, headers=_headers(), params=params, json=body, timeout=30
        )

    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text}

    ok = resp.status_code < 400
    _log(f"{'OK' if ok else 'FAIL'} {resp.status_code}")
    return {"success": ok, "status": resp.status_code, "data": data}


# ── Core: My Messages ────────────────────────────────────────────

def _get_my_email() -> str:
    """Get the signed-in user's email for client-side filtering."""
    result = me()
    if not result["success"]:
        _die("Failed to get user profile — cannot determine your identity")
    data = result["data"]
    email = data.get("mail") or data.get("userPrincipalName", "")
    if not email:
        _die("Could not determine your email address from /me")
    _log(f"Filtering messages from: {email}")
    return email.lower()


def my_messages(keyword: Optional[str] = None, top: int = 25) -> Dict[str, Any]:
    """Retrieve only the signed-in user's own messages via Graph Search API.

    The Search API's `from:me` KQL does NOT work for chatMessage entity
    type, so we fetch messages and filter client-side by matching the
    sender email against the signed-in user's email from /me.

    Optionally filters by keyword for further narrowing.
    Returns chat AND channel messages.
    """
    my_email = _get_my_email()

    # Build KQL query — just the keyword (from:me is unreliable for chatMessages)
    kql = keyword if keyword else "*"

    all_hits: List[Dict[str, Any]] = []
    offset = 0
    page_size = 25  # Graph Search caps at 25 per page
    max_pages = 20  # Safety limit to avoid infinite loops

    pages_fetched = 0
    while len(all_hits) < top and pages_fetched < max_pages:
        pages_fetched += 1
        result = graph(
            "/search/query",
            method="POST",
            body={
                "requests": [
                    {
                        "entityTypes": ["chatMessage"],
                        "query": {"queryString": kql},
                        "from": offset,
                        "size": page_size,
                    }
                ]
            },
        )

        if not result["success"]:
            return result

        # Extract hits from the response
        containers = (
            result.get("data", {}).get("value", [{}])[0].get("hitsContainers", [])
        )
        if not containers:
            break

        container = containers[0]
        hits = container.get("hits", [])
        if not hits:
            break

        # Client-side filter: only keep messages sent by the signed-in user
        for hit in hits:
            resource = hit.get("resource", {})
            from_info = resource.get("from", {})
            sender_email = ""
            if from_info.get("emailAddress"):
                sender_email = from_info["emailAddress"].get("address", "").lower()
            elif from_info.get("user"):
                # Fallback: some results use user.id instead of emailAddress
                sender_email = from_info["user"].get("userPrincipalName", "").lower()

            if sender_email == my_email:
                all_hits.append(hit)
                if len(all_hits) >= top:
                    break

        # Check if more results are available
        more = container.get("moreResultsAvailable", False)
        if not more:
            break

        offset += len(hits)

    # Trim to requested count
    all_hits = all_hits[:top]

    return {
        "success": True,
        "status": 200,
        "data": {
            "total": len(all_hits),
            "hits": all_hits,
        },
    }


def me() -> Dict[str, Any]:
    """Return the signed-in user's profile."""
    return graph("/me")


def list_chats(top: int = 20) -> Dict[str, Any]:
    """List the signed-in user's chats, ordered by most recent."""
    return graph(
        "/me/chats",
        params={
            "$top": top,
            "$expand": "members",
        },
    )


def chat_messages(chat_id: str, top: int = 20) -> Dict[str, Any]:
    """Read messages from a 1:1 or group chat."""
    return graph(f"/me/chats/{chat_id}/messages", params={"$top": top})


def find_chat_by_topic(
    topic_query: str, max_pages: int = 10
) -> Optional[Dict[str, Any]]:
    """Find a chat by topic name, paginating through /me/chats.

    Performs a case-insensitive substring match of *topic_query* against
    each chat's topic.  Paginates through up to *max_pages* pages (≤50
    chats each) so that even older / less-active chats can be found.

    Returns the first matching chat object (with members expanded),
    or ``None`` if nothing matches.
    """
    query_lower = topic_query.lower()
    page = 0
    result = graph("/me/chats", params={"$top": 50, "$expand": "members"})

    while result and result.get("success"):
        page += 1
        chats = result["data"].get("value", [])
        _log(f"find_chat_by_topic: page {page}, {len(chats)} chats")

        for chat in chats:
            topic = (chat.get("topic") or "").lower()
            if query_lower in topic:
                _log(f"Matched chat: {chat.get('topic')} ({chat['id']})")
                return chat

        next_link = result["data"].get("@odata.nextLink")
        if not next_link or page >= max_pages:
            break
        result = graph(next_link)

    _log(f"No chat found matching topic '{topic_query}' after {page} page(s)")
    return None


def find_chat_messages(
    topic_query: str, top: int = 20, max_pages: int = 10
) -> Dict[str, Any]:
    """Find a chat by topic and return its last *top* messages.

    Combines :func:`find_chat_by_topic` and :func:`chat_messages` into a
    single convenience call.  Returns a standard result envelope with an
    extra ``chat`` key containing the matched chat metadata.
    """
    chat = find_chat_by_topic(topic_query, max_pages=max_pages)
    if chat is None:
        return {
            "success": False,
            "status": 404,
            "data": {"error": f"No chat found matching topic '{topic_query}'"},
        }

    result = chat_messages(chat["id"], top=top)
    # Attach matched chat info for context
    result["chat"] = {
        "id": chat["id"],
        "topic": chat.get("topic"),
        "chatType": chat.get("chatType"),
        "memberCount": len(chat.get("members", [])),
    }
    return result


def find_chat_by_member(
    member_query: str,
    chat_type: Optional[str] = None,
    max_pages: int = 10,
) -> Optional[Dict[str, Any]]:
    """Find a chat by member display name, paginating through /me/chats.

    Performs a case-insensitive substring match of *member_query* against
    each member's ``displayName`` in all chats.

    Args:
        member_query: Substring to match against member display names
            (e.g. ``"Sakhnovsky"`` or ``"Hauser, Orli"``).
        chat_type: Optional filter — ``"oneOnOne"`` for 1:1 chats,
            ``"group"`` for group chats, or ``None`` for any type.
        max_pages: Maximum pages to scan (each page ≤ 50 chats).

    Returns the first matching chat object (with members expanded),
    or ``None`` if nothing matches.
    """
    query_lower = member_query.lower()
    page = 0
    result = graph("/me/chats", params={"$top": 50, "$expand": "members"})

    while result and result.get("success"):
        page += 1
        chats = result["data"].get("value", [])
        _log(f"find_chat_by_member: page {page}, {len(chats)} chats")

        for chat in chats:
            # Filter by chat type if requested
            if chat_type and chat.get("chatType") != chat_type:
                continue
            for m in chat.get("members", []):
                dn = (m.get("displayName") or "").lower()
                if query_lower in dn:
                    topic = chat.get("topic") or "(no topic)"
                    ctype = chat.get("chatType", "?")
                    members = [mb.get("displayName", "?") for mb in chat.get("members", [])]
                    _log(f"Matched {ctype} chat: {topic} — members: {', '.join(members)}")
                    return chat

        next_link = result["data"].get("@odata.nextLink")
        if not next_link or page >= max_pages:
            break
        result = graph(next_link)

    _log(f"No chat found with member matching '{member_query}' after {page} page(s)")
    return None


def find_member_chat_messages(
    member_query: str,
    top: int = 20,
    chat_type: Optional[str] = None,
    max_pages: int = 10,
) -> Dict[str, Any]:
    """Find a chat by member name and return its last *top* messages.

    Combines :func:`find_chat_by_member` and :func:`chat_messages` into a
    single convenience call.  Preferred for 1:1 chats which have no topic.

    By default searches all chat types.  Pass ``chat_type="oneOnOne"`` to
    restrict to 1:1 conversations.
    """
    chat = find_chat_by_member(member_query, chat_type=chat_type, max_pages=max_pages)
    if chat is None:
        return {
            "success": False,
            "status": 404,
            "data": {"error": f"No chat found with member matching '{member_query}'"},
        }

    result = chat_messages(chat["id"], top=top)
    members = [mb.get("displayName", "?") for mb in chat.get("members", [])]
    result["chat"] = {
        "id": chat["id"],
        "topic": chat.get("topic"),
        "chatType": chat.get("chatType"),
        "members": members,
        "memberCount": len(members),
    }
    return result


# ── Pretty Formatters ────────────────────────────────────────────

def _fmt_hit(hit: dict) -> str:
    """Format a single search hit into readable text."""
    resource = hit.get("resource", {})

    # Sender
    sender = "Unknown"
    f = resource.get("from", {})
    if f and f.get("user"):
        sender = f["user"].get("displayName", f["user"].get("id", "?"))
    elif f and f.get("emailAddress"):
        sender = f["emailAddress"].get("name", f["emailAddress"].get("address", "?"))

    # Timestamp
    ts = resource.get("createdDateTime", "")

    # Body
    body = resource.get("body", {})
    content = body.get("content", "")
    if body.get("contentType") == "html":
        content = strip_html(content)
    # Also check the summary field from Search API
    summary = hit.get("summary", "")

    # Use content if available, otherwise fall back to summary
    text = content.strip() if content.strip() else summary.strip()

    # Chat/channel context
    chat_id = resource.get("chatId", "")
    channel_id = resource.get("channelIdentity", {})
    context_line = ""
    if channel_id:
        team_id = channel_id.get("teamId", "?")
        chan_id = channel_id.get("channelId", "?")
        context_line = f"  [Channel] Team: {team_id[:8]}… Channel: {chan_id[:8]}…"
    elif chat_id:
        context_line = f"  [Chat] {chat_id[:20]}…"

    # Attachments
    atts = resource.get("attachments", [])
    att_line = ""
    if atts:
        names = [a.get("name", "?") for a in atts]
        att_line = f"\n  Attachments: {', '.join(names)}"

    line = f"[{ts}] {sender}:\n  {text}"
    if context_line:
        line += f"\n{context_line}"
    if att_line:
        line += att_line

    return line


def _fmt_msg(m: dict) -> str:
    """Format a single chat/channel message into readable text."""
    sender = "Unknown"
    f = m.get("from")
    if f and f.get("user"):
        sender = f["user"].get("displayName", f["user"].get("id", "?"))
    ts = m.get("createdDateTime", "")
    body = m.get("body", {})
    content = body.get("content", "")
    if body.get("contentType") == "html":
        content = strip_html(content)
    subj = m.get("subject")
    line = f"[{ts}] {sender}:"
    if subj:
        line += f" ({subj})"
    line += f"\n  {content}"
    atts = m.get("attachments", [])
    if atts:
        names = [a.get("name", "?") for a in atts]
        line += f"\n  Attachments: {', '.join(names)}"
    return line


def pretty(result: Dict[str, Any]) -> str:
    """Format the full result as human-readable text."""
    # Search API results (--my-messages)
    hits = result.get("data", {}).get("hits", [])
    if hits:
        total = result.get("data", {}).get("total", len(hits))
        header = f"Found {total} message(s) from you:\n" + "─" * 50
        return header + "\n\n" + "\n\n".join(_fmt_hit(h) for h in hits)
    # Direct Graph API results (--chat-messages, --chats)
    msgs = result.get("data", {}).get("value", [])
    if msgs:
        return "\n\n".join(_fmt_msg(m) for m in msgs)
    return "No messages found."


# ── Utilities ─────────────────────────────────────────────────────

def _log(msg: str):
    print(f"[my-msgs] {msg}", file=sys.stderr)


def _die(msg: str):
    print(f"[my-msgs] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


# ── CLI ───────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Retrieve only YOUR OWN Teams messages (Graph Search API)"
    )

    p.add_argument(
        "--my-messages", action="store_true",
        help="Retrieve your own messages from chats and channels",
    )
    p.add_argument("--me", action="store_true", help="Show signed-in user profile")
    p.add_argument("--chats", action="store_true", help="List your chats")
    p.add_argument("--chat-messages", metavar="CHAT", help="Read messages from a chat")
    p.add_argument(
        "--find-chat", metavar="TOPIC",
        help="Find a chat by topic name and return its messages",
    )
    p.add_argument(
        "--find-member", metavar="NAME",
        help="Find a chat by member display name and return its messages "
             "(e.g. 'Sakhnovsky, Lev'). Searches 1:1 first, then group chats.",
    )
    p.add_argument(
        "--keyword", metavar="TEXT",
        help="Optional keyword to filter your messages (combined with from:me)",
    )
    p.add_argument(
        "--top", type=int, default=25,
        help="Number of messages to return (default 25)",
    )
    p.add_argument("--pretty", action="store_true", help="Human-readable output")
    p.add_argument(
        "--clear-cache", action="store_true",
        help="Delete cached tokens and exit",
    )

    args = p.parse_args()

    # Handle cache clear
    if args.clear_cache:
        if os.path.exists(TOKEN_CACHE):
            os.remove(TOKEN_CACHE)
            print("Token cache deleted.")
        else:
            print("No token cache found.")
        return

    # Dispatch
    result = None

    if args.me:
        result = me()
    elif args.chats:
        result = list_chats(top=args.top)
    elif args.chat_messages:
        result = chat_messages(args.chat_messages, top=args.top)
    elif args.find_chat:
        result = find_chat_messages(args.find_chat, top=args.top)
    elif args.find_member:
        # Try 1:1 first, fall back to any chat type
        result = find_member_chat_messages(
            args.find_member, top=args.top, chat_type="oneOnOne"
        )
        if not result.get("success"):
            _log("No 1:1 chat found, searching group chats…")
            result = find_member_chat_messages(
                args.find_member, top=args.top, chat_type="group"
            )
    elif args.my_messages:
        result = my_messages(keyword=args.keyword, top=args.top)
    else:
        p.print_help()
        sys.exit(1)

    # Output
    if args.pretty and result.get("success"):
        print(pretty(result))
    else:
        print(json.dumps(result, indent=2))

    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
