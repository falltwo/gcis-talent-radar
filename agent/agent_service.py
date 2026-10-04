"""Backward-compatible service entry point for the OpenRouter agent."""

from agent.llm_agent import OpenRouterAgent, OpenRouterError, agent_service

__all__ = ["OpenRouterAgent", "OpenRouterError", "agent_service"]
