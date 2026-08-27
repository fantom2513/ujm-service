from __future__ import annotations

import logging

import httpx

from app.infrastructure.jira.errors import JiraError

logger = logging.getLogger(__name__)


class JiraClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout_ms: int = 30_000,
        insecure_tls: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout_ms = timeout_ms
        self._verify = not insecure_tls

    async def get_issue(self, key: str) -> dict:
        """Fetches an issue's summary/description by key (e.g. "ABC-123").
        Never lets httpx exceptions escape as-is — every failure is
        converted to a `JiraError` with one of: UNAUTHORIZED, NOT_FOUND,
        HTTP_ERROR, TIMEOUT, NETWORK_ERROR.
        """
        url = f"{self.base_url}/rest/api/2/issue/{key}"
        timeout = httpx.Timeout(self.timeout_ms / 1000)
        auth = (self.username, self.password)

        try:
            async with httpx.AsyncClient(auth=auth, verify=self._verify, timeout=timeout) as client:
                response = await client.get(url, params={"fields": "summary,description"})
            response.raise_for_status()
        except httpx.TimeoutException as err:
            logger.exception("Jira request timed out for issue %s", key)
            raise JiraError("TIMEOUT", f"Jira timed out after {self.timeout_ms}ms") from err
        except httpx.HTTPStatusError as err:
            status = err.response.status_code
            if status in (401, 403):
                logger.warning("Jira rejected credentials for issue %s (HTTP %d)", key, status)
                raise JiraError("UNAUTHORIZED", "Jira authentication failed") from err
            if status == 404:
                logger.warning("Jira issue %s not found", key)
                raise JiraError("NOT_FOUND", f"Jira issue {key} not found") from err
            # Body is truncated and never logged in full — it can echo the
            # Authorization header back on some Jira proxies/gateways.
            body = err.response.text[:400]
            logger.exception("Jira HTTP %d for issue %s: %s", status, key, body)
            raise JiraError("HTTP_ERROR", f"Jira HTTP {status}: {body}") from err
        except httpx.HTTPError as err:
            logger.exception("Jira network error for issue %s", key)
            raise JiraError("NETWORK_ERROR", f"Jira network error: {err}") from err

        fields = response.json().get("fields", {})
        return {
            "summary": fields.get("summary") or "",
            "description": fields.get("description") or "",
        }
