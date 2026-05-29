"""Learning-insights federation surface.

This subpackage owns the read-side aggregation for ``/learn`` insights:
the operator-local :class:`mureo.core.knowledge_store.KnowledgeStore`
combined with zero or more external MCP servers configured in
``~/.mureo/insight_sources.json``. The MCP tool
:data:`mureo.mcp.tools_learning.mureo_learning_insights_get` consumes
the aggregator, so a third party who runs their own insights MCP
server (consulting know-how, industry benchmarks, community wisdom)
can be federated in without changing the tool's public shape.
"""
