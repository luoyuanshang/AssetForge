"""A small OpenAI-compatible model client for generation and review."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class ModelEndpoint:
    def __init__(self, *, role="author", base_url=None, api_key=None, model=None, timeout=None):
        if role not in ("author", "reviewer"):
            raise ValueError("role must be author or reviewer")
        prefix = "ASSETFORGE_REVIEWER_" if role == "reviewer" else "ASSETFORGE_"
        self.base_url = base_url or os.environ.get(prefix + "API_BASE_URL") or os.environ.get("ASSETFORGE_API_BASE_URL")
        self.api_key = api_key or os.environ.get(prefix + "API_KEY") or os.environ.get("ASSETFORGE_API_KEY")
        self.model = model or os.environ.get(prefix + "MODEL")
        self.timeout = float(timeout if timeout is not None else os.environ.get("ASSETFORGE_TIMEOUT_SECONDS", "3600"))
        if not self.base_url or not self.base_url.startswith(("http://", "https://")):
            raise ValueError("set an absolute ASSETFORGE_API_BASE_URL")
        if not self.api_key:
            raise ValueError("set ASSETFORGE_API_KEY")
        if not self.model:
            raise ValueError("set " + prefix + "MODEL")
        if self.timeout <= 0:
            raise ValueError("request timeout must be positive")

    def chat(self, messages):
        request = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps({"model": self.model, "messages": messages, "temperature": 0.0}).encode(),
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"model request failed: HTTP {exc.code}") from None
        except urllib.error.URLError:
            raise RuntimeError("model endpoint is unreachable") from None
        if not isinstance(result, dict):
            raise ValueError("model endpoint returned a non-object response")
        return result
