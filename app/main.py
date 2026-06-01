"""Streamlit エントリ。工場設備管理デモのチャット UI。"""

from __future__ import annotations

import json
import os

# Bedrock の Bearer 認証を boto3 に渡すためのブリッジ。
# Strands Agents(Python) は BEDROCK_API_KEY を直接サポートしないため、
# boto3 が解釈する AWS_BEARER_TOKEN_BEDROCK にコピーする。
if os.getenv("BEDROCK_API_KEY") and not os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = os.environ["BEDROCK_API_KEY"]

import streamlit as st

from agent import build_agent
from auth import ROLES, get_role
from system_prompt import DB_DESCRIPTIONS, FACTORY_NAMES


QUERY_TOOL_NAMES = {"mysql_query", "postgres_query"}


def format_executed_queries(tool_calls_log: list[dict]) -> str:
    """ツール呼び出しログから実行された SELECT クエリを抜き出して Markdown 化する。"""
    seen: set[tuple[str, str]] = set()
    entries: list[tuple[str, str]] = []
    for tc in tool_calls_log:
        if tc.get("name") not in QUERY_TOOL_NAMES:
            continue
        raw = tc.get("input", "")
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        database = payload.get("database")
        sql = payload.get("sql")
        if not database or not sql:
            continue
        sql = sql.strip()
        key = (database, sql)
        if key in seen:
            continue
        seen.add(key)
        entries.append(key)

    if not entries:
        return ""

    lines = ["", "---", "### 実行したクエリ", ""]
    for idx, (database, sql) in enumerate(entries, start=1):
        meta = DB_DESCRIPTIONS.get(database)
        if meta:
            header = f"**{idx}. {meta['label']} [`{database}` / {meta['engine']}]**"
        else:
            header = f"**{idx}. `{database}`**"
        lines.append(header)
        lines.append("```sql")
        lines.append(sql)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


SAMPLE_QUESTIONS = {
    "tokyo_designer": [
        "東京工場の第2ラインの昨日の生産実績と不良率を見せて",
        "ベアリング系の部品の設計変更履歴を直近で教えて",
    ],
    "tokyo_buyer": [
        "東京製鋼株式会社からの発注で納期遅れリスクがあるものは?",
        "在庫が 50 個未満の部品とそのサプライヤーを一覧で",
    ],
    "tokyo_operator": [
        "東京工場の第2ラインの昨日の稼働率を計算して",
        "東京工場の在庫が少ない部品トップ 5",
    ],
    "osaka_designer": [
        "大阪工場の第1ラインの品質指標(不良率)を直近 1 週間で",
        "大阪工場で最近変更された部品の BOM ツリーを見せて",
    ],
    "osaka_buyer": [
        "大阪工場で使う部品で発注リードタイムが長いトップ 5",
        "大阪工場の在庫推移(直近 1 週間の出庫量)",
    ],
    "osaka_operator": [
        "大阪工場の第3ラインで停止が多かった時間帯は?",
        "大阪工場の在庫アラート(残量 30 未満)を出して",
    ],
    "quality_manager": [
        "全社でこの 1 週間に不良率が悪化したラインは?",
        "不良が多い部品トップ 5 と、その設計変更履歴",
    ],
    "admin": [
        "全社の稼働率トップ 3 ラインと、対応するサプライヤーの納期遵守率",
        "大阪工場の不良が多かった日トップ 3 と、その日に該当部品の入庫があったか",
        "全 DB の現在のテーブル一覧を出して",
    ],
}


def main() -> None:
    st.set_page_config(page_title="Factory MCP Demo", page_icon=":factory:", layout="wide")

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "role_key" not in st.session_state:
        st.session_state.role_key = "admin"

    with st.sidebar:
        st.title("Factory MCP Demo")
        st.caption("自然言語の問い合わせを LLM が複数 DB(MySQL/PostgreSQL)に MCP 経由で展開します。")

        role_keys = list(ROLES.keys())
        role_key = st.selectbox(
            "ロールを選択",
            options=role_keys,
            index=role_keys.index(st.session_state.role_key),
            format_func=lambda k: ROLES[k].label,
        )
        if role_key != st.session_state.role_key:
            st.session_state.role_key = role_key
            st.session_state.messages = []

        role = get_role(role_key)
        st.markdown("**アクセス可能な DB**")
        for db in role.allowed_databases:
            label = DB_DESCRIPTIONS[db]["label"]
            st.markdown(f"- {label} (`{db}`)")
        if role.is_all_factories:
            st.markdown("**拠点スコープ:** 全社")
        else:
            scope = " / ".join(FACTORY_NAMES[i] for i in role.factory_ids)
            st.markdown(f"**拠点スコープ:** {scope}")

        st.divider()
        st.markdown("**サンプル質問**")
        for q in SAMPLE_QUESTIONS.get(role_key, []):
            if st.button(q, key=f"sample_{q}", use_container_width=True):
                st.session_state.pending_question = q

        if st.button("会話をリセット", use_container_width=True):
            st.session_state.messages = []

    st.title(f"工場設備管理デモ — {ROLES[st.session_state.role_key].label}")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            for tc in msg.get("tool_calls", []):
                with st.expander(f"ツール呼び出し: {tc['name']}"):
                    st.code(tc.get("input", ""), language="json")
                    st.code(tc.get("output", ""), language="json")

    pending = st.session_state.pop("pending_question", None)
    user_input = st.chat_input("質問を入力(例: 東京工場の第2ラインの昨日の稼働率は?)")
    question = pending or user_input

    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            answer_placeholder = st.empty()
            tool_calls_log: list[dict] = []
            status_placeholder = st.status("LLM が回答を生成中…", expanded=False)
            try:
                role = get_role(st.session_state.role_key)
                with build_agent(role) as agent:
                    result = agent(question)
                    answer = str(result)

                    for msg_obj in getattr(agent, "messages", [])[-10:]:
                        content = getattr(msg_obj, "content", None) or msg_obj.get("content") if isinstance(msg_obj, dict) else None
                        if isinstance(content, list):
                            for item in content:
                                if isinstance(item, dict) and "toolUse" in item:
                                    tu = item["toolUse"]
                                    tool_calls_log.append({
                                        "name": tu.get("name", ""),
                                        "input": str(tu.get("input", "")),
                                        "output": "",
                                    })
                                if isinstance(item, dict) and "toolResult" in item:
                                    tr = item["toolResult"]
                                    if tool_calls_log:
                                        tool_calls_log[-1]["output"] = str(tr.get("content", ""))
                status_placeholder.update(label="完了", state="complete")
                answer = answer + format_executed_queries(tool_calls_log)
            except Exception as e:
                answer = f"エラーが発生しました: {e}"
                status_placeholder.update(label="エラー", state="error")

            answer_placeholder.markdown(answer)
            for tc in tool_calls_log:
                with st.expander(f"ツール呼び出し: {tc['name']}"):
                    st.code(tc["input"], language="json")
                    st.code(tc["output"], language="json")

            st.session_state.messages.append({
                "role": "assistant",
                "content": answer,
                "tool_calls": tool_calls_log,
            })


if __name__ == "__main__":
    main()
