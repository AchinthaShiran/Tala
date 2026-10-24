"""Compile the agent graph (see ADR-001).

route ─► chat ─► END
  └────► executor ─► authorize ─► run_tools ─┬─► executor (next step)
            │  ▲___________________________  └─► summarizer ─► END
            └─► chat (no tool fits)   └ repair: executor
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from assistant.agent.nodes import AgentDeps, AgentNodes
from assistant.agent.state import AgentState


def _next(state: AgentState) -> str:
    return state.get("next", "chat")


def build_graph(
    deps: AgentDeps, checkpointer: BaseCheckpointSaver[Any] | None = None
) -> CompiledStateGraph[Any, Any, Any, Any]:
    nodes = AgentNodes(deps)
    graph: StateGraph[AgentState] = StateGraph(AgentState)
    graph.add_node("route", nodes.route)
    graph.add_node("chat", nodes.chat)
    graph.add_node("executor", nodes.execute_plan)
    graph.add_node("fast", nodes.fast_path)
    graph.add_node("authorize", nodes.authorize)
    graph.add_node("run_tools", nodes.run_tools)
    graph.add_node("summarizer", nodes.summarize)

    graph.add_edge(START, "route")
    graph.add_conditional_edges(
        "route", _next, {"executor": "executor", "chat": "chat", "fast": "fast"}
    )
    graph.add_conditional_edges("fast", _next, {"authorize": "authorize", "executor": "executor"})
    graph.add_conditional_edges(
        "executor",
        _next,
        {
            "authorize": "authorize",
            "executor": "executor",
            "summarizer": "summarizer",
            "chat": "chat",
            "end": END,
        },
    )
    graph.add_edge("authorize", "run_tools")
    graph.add_conditional_edges(
        "run_tools", _next, {"executor": "executor", "summarizer": "summarizer"}
    )
    graph.add_edge("chat", END)
    graph.add_edge("summarizer", END)
    return graph.compile(checkpointer=checkpointer)
