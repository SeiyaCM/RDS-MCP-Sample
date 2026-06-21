"""Strands Agents 構築。2 つの MCP サーバー(MySQL/Postgres)を統合する。

Strands の `MCPClient` はコンテキストマネージャ前提なので、Streamlit の各リクエストで
都度 enter/exit する。MCP サーバーは Streamable HTTP のステートレスモードで動かしており、
各リクエストは完全に独立した HTTP リクエスト/レスポンスで完結する。
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Callable, Iterator

import httpx
from mcp.client.streamable_http import streamable_http_client
from strands import Agent
from strands.hooks import BeforeToolCallEvent, HookProvider
from strands.hooks.registry import HookRegistry
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient

from auth import Role
from system_prompt import build_system_prompt

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = int(os.environ.get("AGENT_MAX_TOOL_CALLS", "20"))


class _ToolCallLimiter(HookProvider):
    """ツール呼び出し回数を MAX_TOOL_CALLS に制限する Hook。

    Strands Agents はデフォルトでツール呼び出し回数に上限がないため、LLM が同じ
    エラーをリトライし続けると永遠に終わらない。BeforeToolCallEvent で回数を数え、
    上限を超えたら invocation_state["request_state"]["stop_event_loop"] = True を
    セットしてループを強制終了する。
    """

    def __init__(self) -> None:
        self.tool_count = 0

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeToolCallEvent, self._on_before_tool_call)

    def _on_before_tool_call(self, event: BeforeToolCallEvent) -> None:
        self.tool_count += 1
        tool_name = event.tool_use.get("name", "")
        logger.info("Tool #%d: %s", self.tool_count, tool_name)

        if self.tool_count > MAX_TOOL_CALLS:
            logger.warning("Tool call limit (%d) reached at tool '%s', stopping event loop.", MAX_TOOL_CALLS, tool_name)
            request_state = event.invocation_state.get("request_state")
            if isinstance(request_state, dict):
                request_state["stop_event_loop"] = True
            event.cancel_tool = f"ツール呼び出し回数が上限({MAX_TOOL_CALLS}回)を超えました。これ以上のツール呼び出しは中止します。現在得られている情報をもとに回答してください。"


def _transport_factory(url: str, allowed_databases: tuple[str, ...]) -> Callable[[], object]:
    """ロールの許可 DB を X-Allowed-Databases ヘッダに載せる transport callable を返す。

    streamable_http_client (mcp 1.27.x) は headers= を直接受け付けないため、
    ヘッダを設定した httpx.AsyncClient を http_client= に渡す。MCP サーバーは
    このヘッダを読んで DB アクセスを実強制する(プロンプトのソフト統制とは別の実防御)。
    strands の MCPClient は渡した callable を zero-arg でそのまま呼ぶので、ここが注入点。
    """
    headers = {"X-Allowed-Databases": ",".join(allowed_databases)}
    return lambda: streamable_http_client(url, http_client=httpx.AsyncClient(headers=headers))


def _bedrock_model() -> BedrockModel:
    model_id = os.environ.get("BEDROCK_MODEL_ID", "us.amazon.nova-lite-v1:0")
    region = os.environ.get("AWS_REGION", "us-east-1")
    return BedrockModel(model_id=model_id, region_name=region, max_tokens=4096)


@contextmanager
def build_agent(role: Role) -> Iterator[Agent]:
    """Strands Agent をロール別に構築する。with 文で使うこと。"""
    mysql_url = os.environ["MCP_MYSQL_URL"]
    postgres_url = os.environ["MCP_POSTGRES_URL"]

    mysql_client = MCPClient(_transport_factory(mysql_url, role.allowed_databases))
    postgres_client = MCPClient(_transport_factory(postgres_url, role.allowed_databases))

    with mysql_client, postgres_client:
        tools = mysql_client.list_tools_sync() + postgres_client.list_tools_sync()
        agent = Agent(
            model=_bedrock_model(),
            tools=tools,
            system_prompt=build_system_prompt(role),
            hooks=[_ToolCallLimiter()],
        )
        yield agent
