"""
Dify API 客户端封装

目标：
- 兼容 Chat App 与 Workflow App 两种调用方式
- 对上层暴露与 DeepSeekClient 近似的 `chat` / `structured_chat` 接口
- 让 WebDemo 后端可以代理 Dify API，而不是前端直连
"""
from __future__ import annotations

import json
import logging
import re
import socket
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from article_check.config.settings import config
from article_check.llm.client.deepseek import LLMResponse

logger = logging.getLogger(__name__)


# #region debug-point A:dify-runtime-observe
def _debug_server_config() -> tuple[str, str]:
    url = "http://host.docker.internal:7777/event"
    session_id = "dify-ipv4-egress"
    env_path = Path(".dbg/dify-ipv4-egress.env")
    try:
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.startswith("DEBUG_SERVER_URL="):
                    url = line.split("=", 1)[1].strip() or url
                elif line.startswith("DEBUG_SESSION_ID="):
                    session_id = line.split("=", 1)[1].strip() or session_id
    except Exception:
        pass
    return url, session_id


def _debug_post(hypothesis_id: str, location: str, msg: str, data: Optional[Dict[str, Any]] = None) -> None:
    try:
        url, session_id = _debug_server_config()
        payload = {
            "sessionId": session_id,
            "runId": "pre-fix",
            "hypothesisId": hypothesis_id,
            "location": location,
            "msg": f"[DEBUG] {msg}",
            "data": data or {},
            "ts": int(time.time() * 1000),
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        pass


def _debug_dns_snapshot(hostname: str) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {"hostname": hostname}
    try:
        snapshot["ipv4"] = sorted({item[4][0] for item in socket.getaddrinfo(hostname, 443, socket.AF_INET, socket.SOCK_STREAM)})
    except Exception as exc:
        snapshot["ipv4_error"] = str(exc)
    try:
        snapshot["ipv6"] = sorted({item[4][0] for item in socket.getaddrinfo(hostname, 443, socket.AF_INET6, socket.SOCK_STREAM)})
    except Exception as exc:
        snapshot["ipv6_error"] = str(exc)
    return snapshot


def _debug_host_from_url(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0].strip()
# #endregion


class DifyClient:
    """Dify Service API 客户端。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        app_type: Optional[str] = None,
        response_mode: Optional[str] = None,
        user: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        cfg = config.dify
        self.api_key = api_key or cfg.api_key
        self.base_url = (base_url or cfg.base_url).rstrip("/")
        self.app_type = (app_type or cfg.app_type or "chat").lower()
        self.response_mode = response_mode or cfg.response_mode
        self.user = user or cfg.user
        self.timeout = timeout or cfg.timeout
        self.workflow_query_key = cfg.workflow_query_key
        self.default_inputs = self._parse_inputs(cfg.inputs_json)

        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        # #region debug-point A:dify-client-init
        _debug_post(
            "A",
            "article_check.llm.client.dify:DifyClient.__init__",
            "initialized dify client",
            {
                "base_url": self.base_url,
                "app_type": self.app_type,
                "response_mode": self.response_mode,
                "dns": _debug_dns_snapshot(_debug_host_from_url(self.base_url)),
            },
        )
        # #endregion

        if not self.api_key:
            logger.warning("DIFY_API_KEY 未配置。")

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        response_format: Optional[Dict] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        stream: bool = False,
    ) -> LLMResponse:
        """将 messages 编译成 Dify 可消费的 prompt 并调用。"""
        del tools, response_format, temperature, max_tokens, model  # Dify 由应用侧配置

        prompt = self._compile_messages(messages)
        start = time.time()

        if self.app_type in {"workflow", "workflow_app"}:
            data = self.run_workflow(
                inputs={self.workflow_query_key: prompt},
                stream=stream,
            )
        else:
            data = self.run_chat_app(
                query=prompt,
                stream=stream,
            )

        elapsed = time.time() - start
        content, usage = self._extract_content_and_usage(data)
        return LLMResponse(
            content=content,
            role="assistant",
            tool_calls=[],
            usage=usage,
            model=f"dify:{self.app_type}",
            latency=elapsed,
        )

    def run_chat_app(
        self,
        query: str,
        *,
        inputs: Optional[Dict[str, Any]] = None,
        files: Optional[List[Dict[str, Any]]] = None,
        conversation_id: str = "",
        user: Optional[str] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "inputs": {
                **self.default_inputs,
                **(inputs or {}),
            },
            "query": query,
            "response_mode": "streaming" if stream else self.response_mode,
            "user": user or self.user,
            "conversation_id": conversation_id,
        }
        if files:
            payload["files"] = files
        return self._post_json("/chat-messages", payload)

    def run_workflow(
        self,
        inputs: Dict[str, Any],
        *,
        user: Optional[str] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        payload = {
            "inputs": {
                **self.default_inputs,
                **inputs,
            },
            "response_mode": "streaming" if stream else self.response_mode,
            "user": user or self.user,
        }
        return self._post_json("/workflows/run", payload)

    def upload_file(
        self,
        file_path: str | Path,
        *,
        user: Optional[str] = None,
        mime_type: str = "application/octet-stream",
    ) -> Dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Dify upload file not found: {path}")

        with path.open("rb") as file_handle:
            try:
                response = httpx.post(
                    f"{self.base_url}/files/upload",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={"file": (path.name, file_handle, mime_type)},
                    data={"user": user or self.user},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException:
                logger.error("Dify 文件上传超时: %s", path)
                raise
            except httpx.HTTPStatusError as exc:
                logger.error("Dify 文件上传 HTTP 错误: %s %s", exc.response.status_code, exc.response.text)
                raise
            except Exception as exc:
                logger.error("Dify 文件上传失败: %s", exc)
                raise

    def _post_json(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            # #region debug-point B:dify-request-start
            _debug_post(
                "B",
                "article_check.llm.client.dify:DifyClient._post_json",
                "sending dify request",
                {
                    "endpoint": endpoint,
                    "base_url": self.base_url,
                    "app_type": self.app_type,
                    "response_mode": payload.get("response_mode"),
                    "input_keys": sorted((payload.get("inputs") or {}).keys()),
                },
            )
            # #endregion
            response = self._client.post(endpoint, json=payload)
            response.raise_for_status()
            # #region debug-point C:dify-request-success
            _debug_post(
                "C",
                "article_check.llm.client.dify:DifyClient._post_json",
                "dify request succeeded",
                {
                    "endpoint": endpoint,
                    "status_code": response.status_code,
                },
            )
            # #endregion
            return response.json()
        except httpx.TimeoutException:
            # #region debug-point D:dify-timeout
            _debug_post(
                "D",
                "article_check.llm.client.dify:DifyClient._post_json",
                "dify request timed out",
                {"endpoint": endpoint, "base_url": self.base_url},
            )
            # #endregion
            logger.error("Dify API 请求超时")
            raise
        except httpx.HTTPStatusError as exc:
            # #region debug-point D:dify-http-error
            _debug_post(
                "D",
                "article_check.llm.client.dify:DifyClient._post_json",
                "dify request returned http error",
                {
                    "endpoint": endpoint,
                    "status_code": exc.response.status_code,
                    "body": exc.response.text[:500],
                },
            )
            # #endregion
            logger.error("Dify API HTTP 错误: %s %s", exc.response.status_code, exc.response.text)
            raise
        except Exception as exc:
            # #region debug-point B:dify-network-error
            _debug_post(
                "B",
                "article_check.llm.client.dify:DifyClient._post_json",
                "dify request failed before response",
                {
                    "endpoint": endpoint,
                    "base_url": self.base_url,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "dns": _debug_dns_snapshot(_debug_host_from_url(self.base_url)),
                },
            )
            # #endregion
            logger.error("Dify API 请求失败: %s", exc)
            raise

    def structured_chat(
        self,
        messages: List[Dict[str, Any]],
        schema: Dict[str, Any],
        **kwargs,
    ) -> dict:
        """
        对 Dify 发送“严格 JSON 输出”请求。
        若 Workflow 输出本身就是对象，则直接返回；否则退回文本解析。
        """
        prompt_suffix = (
            "\n\n你必须仅输出一个 JSON 对象，不要包含 markdown 代码块，不要输出解释文字。"
            f"\n请满足以下 JSON Schema：\n{json.dumps(schema, ensure_ascii=False)}"
        )
        patched_messages = list(messages)
        if patched_messages:
            patched_messages[-1] = {
                **patched_messages[-1],
                "content": f"{patched_messages[-1].get('content', '')}{prompt_suffix}",
            }
        else:
            patched_messages = [{"role": "user", "content": prompt_suffix}]

        result = self.chat(messages=patched_messages, **kwargs)
        try:
            return self._parse_structured_json(result.content)
        except json.JSONDecodeError as exc:
            logger.error("Dify 结构化输出解析失败: %s", exc)
            logger.debug("Dify 原始输出: %s", result.content[:800])
            raise

    def _extract_content_and_usage(self, data: Dict[str, Any]) -> tuple[str, Dict[str, int]]:
        usage = (
            data.get("metadata", {}).get("usage")
            or data.get("usage")
            or data.get("data", {}).get("total_tokens")
            or {}
        )
        if isinstance(usage, int):
            usage = {"total_tokens": usage}

        if self.app_type in {"workflow", "workflow_app"}:
            workflow_data = data.get("data", data)
            outputs = workflow_data.get("outputs") or {}
            if isinstance(outputs, dict):
                direct = self._pick_primary_output(outputs)
                if isinstance(direct, (dict, list)):
                    return json.dumps(direct, ensure_ascii=False), usage
                if direct is not None:
                    return str(direct), usage
            answer = workflow_data.get("answer") or workflow_data.get("text") or ""
            if isinstance(answer, (dict, list)):
                answer = json.dumps(answer, ensure_ascii=False)
            return str(answer), usage

        answer = data.get("answer", "")
        if isinstance(answer, (dict, list)):
            answer = json.dumps(answer, ensure_ascii=False)
        return str(answer), usage

    def _pick_primary_output(self, outputs: Dict[str, Any]) -> Any:
        for key in ("answer", "text", "result", "output", "content", "json"):
            if key in outputs:
                return outputs[key]
        if len(outputs) == 1:
            return next(iter(outputs.values()))
        return outputs

    def _compile_messages(self, messages: List[Dict[str, Any]]) -> str:
        compiled: List[str] = []
        for message in messages:
            role = str(message.get("role", "user")).upper()
            content = str(message.get("content", "")).strip()
            if content:
                compiled.append(f"[{role}]\n{content}")
        return "\n\n".join(compiled)

    def _parse_inputs(self, raw: str) -> Dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            logger.warning("DIFY_INPUTS_JSON 解析失败，将使用空 inputs。")
            return {}

    def _parse_structured_json(self, content: str) -> dict:
        candidates = []
        stripped = content.strip()
        if stripped:
            candidates.append(stripped)

        extracted = self._extract_json_object(stripped)
        if extracted and extracted not in candidates:
            candidates.append(extracted)

        for candidate in list(candidates):
            repaired = self._repair_json_text(candidate)
            if repaired and repaired not in candidates:
                candidates.append(repaired)

        last_error: Optional[json.JSONDecodeError] = None
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue

        if last_error:
            raise last_error
        raise json.JSONDecodeError("Empty JSON content", content, 0)

    def _extract_json_object(self, text: str) -> str:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return text
        return text[start:end + 1]

    def _repair_json_text(self, text: str) -> str:
        repaired = text.strip()
        repaired = re.sub(r"^```(?:json)?\s*", "", repaired)
        repaired = re.sub(r"\s*```$", "", repaired)
        repaired = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", repaired)
        repaired = re.sub(r'\\u(?![0-9a-fA-F]{4})', r"\\\\u", repaired)
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
        repaired = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", " ", repaired)
        return repaired

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
