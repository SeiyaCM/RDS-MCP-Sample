"""Strands Agents 構築。2 つの MCP サーバー(MySQL/Postgres)を統合する。

Strands の `MCPClient` はコンテキストマネージャ前提なので、Streamlit の各リクエストで
都度 enter/exit する。MCP サーバーは Streamable HTTP のステートレスモードで動かしており、
各リクエストは完全に独立した HTTP リクエスト/レスポンスで完結する。
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from mcp.client.streamable_http import streamable_http_client
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient

from auth import Role
from system_prompt import build_system_prompt


def _bedrock_model() -> BedrockModel:
    model_id = os.environ.get("BEDROCK_MODEL_ID", "us.amazon.nova-lite-v1:0")
    region = os.environ.get("AWS_REGION", "us-east-1")
    return BedrockModel(model_id=model_id, region_name=region)


@contextmanager
def build_agent(role: Role) -> Iterator[Agent]:
    """Strands Agent をロール別に構築する。with 文で使うこと。"""
    mysql_url = os.environ["MCP_MYSQL_URL"]
    postgres_url = os.environ["MCP_POSTGRES_URL"]

    mysql_client = MCPClient(lambda: streamable_http_client(mysql_url))
    postgres_client = MCPClient(lambda: streamable_http_client(postgres_url))

    with mysql_client, postgres_client:
        tools = mysql_client.list_tools_sync() + postgres_client.list_tools_sync()
        agent = Agent(
            model=_bedrock_model(),
            tools=tools,
            system_prompt=build_system_prompt(role),
        )
        yield agent
