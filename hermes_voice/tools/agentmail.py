"""
agentmail tool — read & send email via AgentMail.to API.

Priority: 30 (between memex8_search and web_search — tries personal
context first, then falls back to general web).

Wraps the AgentMail.to skill (https://docs.agentmail.to/api-reference) so
the voice LLM can ask "check my email" or "send an email to X" and
have it just work.

Operations (chosen by `action` arg):
  - list_inboxes: return all configured inboxes
  - list_messages: return recent messages from an inbox (default: hermes_chillygeek)
  - get_message: return full body of a specific message_id
  - send: send an email (requires to, subject, text)

Reads credentials from env: AGENTMAIL_API_KEY. Optional AGENTMAIL_INBOX
to set the default inbox; defaults to hermes_chillygeek@agentmail.to.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

from .base import Tool, ToolResult
from .registry import register

logger = logging.getLogger("hermes-voice.tools.agentmail")

API_BASE = "https://api.agentmail.to/v0"
DEFAULT_INBOX = "hermes_chillygeek@agentmail.to"


@register
class AgentmailTool(Tool):
    name = "agentmail"
    description = (
        "Read and send email via AgentMail.to. Operations: "
        "list_inboxes (no args), list_messages (inbox optional, limit optional), "
        "get_message (message_id required), send (to, subject, text required). "
        "Use for 'check my email', 'read the latest message from X', "
        "'send an email to Y', etc."
    )
    priority = 30
    examples = [
        '[[TOOL:agentmail action=list_messages limit=5]]',
        '[[TOOL:agentmail action=list_messages inbox="chillygeekbot@agentmail.to" limit=3]]',
        '[[TOOL:agentmail action=get_message message_id="abc123"]]',
        '[[TOOL:agentmail action=send to="user@example.com" subject="Hello" text="Hi there"]]',
    ]

    async def run(
        self,
        action: str = "",
        inbox: str = "",
        message_id: str = "",
        limit: str = "10",
        to: str = "",
        subject: str = "",
        text: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        """Dispatch to the right AgentMail API call based on `action`."""
        api_key = os.getenv("AGENTMAIL_API_KEY", "").strip()
        if not api_key:
            return ToolResult(
                text="",
                success=False,
                source=self.name,
                error="AGENTMAIL_API_KEY not set in gateway .env",
            )

        action = (action or "").strip().lower()
        if not action:
            return ToolResult(
                text="",
                success=False,
                source=self.name,
                error="Missing required 'action' arg. Use: list_inboxes, list_messages, get_message, send",
            )

        headers = {"Authorization": f"Bearer {api_key}"}
        timeout = httpx.Timeout(15.0, connect=5.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if action == "list_inboxes":
                    return await self._list_inboxes(client, headers)
                elif action == "list_messages":
                    target = inbox.strip() or os.getenv("AGENTMAIL_INBOX", "").strip() or DEFAULT_INBOX
                    return await self._list_messages(client, headers, target, limit)
                elif action == "get_message":
                    if not message_id.strip():
                        return ToolResult(text="", success=False, source=self.name, error="get_message requires message_id")
                    target = inbox.strip() or os.getenv("AGENTMAIL_INBOX", "").strip() or DEFAULT_INBOX
                    return await self._get_message(client, headers, target, message_id.strip())
                elif action == "send":
                    if not (to.strip() and subject.strip() and text.strip()):
                        return ToolResult(
                            text="", success=False, source=self.name,
                            error="send requires to, subject, and text",
                        )
                    return await self._send(client, headers, inbox, to.strip(), subject.strip(), text)
                else:
                    return ToolResult(
                        text="", success=False, source=self.name,
                        error=f"Unknown action: {action!r}. Use list_inboxes, list_messages, get_message, or send",
                    )
        except httpx.ConnectError as e:
            return ToolResult(text="", success=False, source=self.name, error=f"network error: {e}")
        except httpx.HTTPStatusError as e:
            return ToolResult(text="", success=False, source=self.name, error=f"HTTP {e.response.status_code}: {e.response.text[:200]}")
        except Exception as e:
            logger.exception("agentmail tool failed")
            return ToolResult(text="", success=False, source=self.name, error=f"{type(e).__name__}: {e}")

    async def _list_inboxes(self, client: httpx.AsyncClient, headers: dict) -> ToolResult:
        resp = await client.get(f"{API_BASE}/inboxes", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        # data is either a list or {inboxes: [...]}
        inboxes = data if isinstance(data, list) else data.get("inboxes", [])
        if not inboxes:
            return ToolResult(text="(no inboxes found)", success=True, source=self.name)
        lines = [f"Configured inboxes ({len(inboxes)}):"]
        for ib in inboxes[:20]:
            email = ib.get("inbox_id") or ib.get("email") or ib.get("address", "?")
            display = ib.get("display_name") or ""
            lines.append(f"- {email}{(' — ' + display) if display else ''}")
        return ToolResult(text="\n".join(lines), success=True, source=self.name)

    async def _list_messages(self, client: httpx.AsyncClient, headers: dict, inbox: str, limit: str) -> ToolResult:
        try:
            n = max(1, min(50, int(limit)))
        except (ValueError, TypeError):
            n = 10
        resp = await client.get(
            f"{API_BASE}/inboxes/{inbox}/messages",
            headers=headers,
            params={"limit": n},
        )
        resp.raise_for_status()
        data = resp.json()
        msgs = data.get("messages", data) if isinstance(data, dict) else data
        if not msgs:
            return ToolResult(text=f"(no messages in {inbox})", success=True, source=self.name)
        lines = [f"Recent messages in {inbox} ({len(msgs)}):"]
        for m in msgs[:n]:
            subj = m.get("subject", "(no subject)")
            frm = m.get("from", "?")
            ts = m.get("timestamp", "")
            mid = m.get("message_id", m.get("id", ""))
            labels = m.get("labels", [])
            unread = " [UNREAD]" if "unread" in labels else ""
            lines.append(f"- {subj}{unread}")
            lines.append(f"  from: {frm}")
            if ts:
                lines.append(f"  when: {ts}")
            if mid:
                lines.append(f"  id: {mid}")
        return ToolResult(text="\n".join(lines), success=True, source=self.name)

    async def _get_message(self, client: httpx.AsyncClient, headers: dict, inbox: str, message_id: str) -> ToolResult:
        resp = await client.get(
            f"{API_BASE}/inboxes/{inbox}/messages/{message_id}",
            headers=headers,
        )
        resp.raise_for_status()
        m = resp.json()
        # Extract text from HTML if present
        html = m.get("html", "")
        text = m.get("text", "")
        if not text and html:
            text = self._html_to_text(html)
        body = text or html or "(empty body)"
        # Truncate very long bodies to keep the LLM prompt small
        if len(body) > 4000:
            body = body[:4000] + f"\n\n[truncated — {len(body) - 4000} more chars]"
        out = [
            f"From: {m.get('from', '?')}",
            f"To: {m.get('to', inbox)}",
            f"Subject: {m.get('subject', '(no subject)')}",
            f"Date: {m.get('timestamp', '')}",
            f"Labels: {m.get('labels', [])}",
            "",
            body,
        ]
        return ToolResult(text="\n".join(out), success=True, source=self.name, data=m)

    async def _send(
        self, client: httpx.AsyncClient, headers: dict, inbox: str,
        to: str, subject: str, text: str,
    ) -> ToolResult:
        from_inbox = inbox.strip() or os.getenv("AGENTMAIL_INBOX", "").strip() or "chillygeekbot@agentmail.to"
        payload = {"to": to, "subject": subject, "text": text}
        resp = await client.post(
            f"{API_BASE}/inboxes/{from_inbox}/messages/send",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        result = resp.json()
        msg_id = result.get("message_id", result.get("id", ""))
        return ToolResult(
            text=f"Email sent from {from_inbox} to {to} (id: {msg_id})",
            success=True, source=self.name, data=result,
        )

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Strip HTML tags for plain-text reading. Mirrors the skill's pattern."""
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
