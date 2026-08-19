"""
OpenTelemetry 全链路追踪模块 v1.0

基于 OpenTelemetry 实现:
  - Agent 执行链路追踪 (Span/Trace)
  - LLM 调用追踪 (token 消耗、延迟、模型)
  - Tool 调用追踪
  - 错误追踪

集成选项:
  1. 本地文件输出 (JSON Lines，开发环境)
  2. Langfuse (生产环境，Agent Graph View)
  3. Arize Phoenix (本地调试，Jupyter Notebook)

架构:
  TracerProvider → SpanProcessor → Exporter
  ├── ConsoleExporter (开发)
  ├── OTLPExporter → Langfuse
  └── FileExporter (JSON Lines)

参考:
  - OpenTelemetry Python SDK v1.28+
  - OpenInference Semantic Conventions for LLM
  - Langfuse OpenTelemetry Integration
"""
import time
import json
import os
import logging
from typing import Optional, Any, Dict, List
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# 尝试导入 OpenTelemetry
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.trace import Status, StatusCode

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    logger.info("OpenTelemetry SDK not installed. Using local file tracing.")


@dataclass
class TraceSpan:
    """追踪 Span (本地回退用)"""
    name: str
    span_id: str
    parent_id: Optional[str]
    start_time: float
    end_time: Optional[float] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict] = field(default_factory=list)
    status: str = "OK"
    error: Optional[str] = None


class LocalTracer:
    """本地追踪器 — 开发环境使用 (无需外部服务)"""

    def __init__(self, service_name: str = "content-moderation"):
        self.service_name = service_name
        self._spans: Dict[str, TraceSpan] = {}
        self._current_span_id: Optional[str] = None
        self._trace_output = os.environ.get(
            "TRACE_OUTPUT", "/workspace/logs/traces.jsonl"
        )
        import uuid
        self._uuid = uuid

    def start_span(self, name: str, attributes: dict = None) -> str:
        """开始一个 Span"""
        span_id = self._uuid.uuid4().hex[:16]
        parent_id = self._current_span_id

        span = TraceSpan(
            name=name,
            span_id=span_id,
            parent_id=parent_id,
            start_time=time.time(),
            attributes=attributes or {},
        )
        self._spans[span_id] = span
        self._current_span_id = span_id
        return span_id

    def end_span(self, span_id: str, attributes: dict = None, error: str = None):
        """结束一个 Span"""
        span = self._spans.get(span_id)
        if not span:
            return

        span.end_time = time.time()
        if attributes:
            span.attributes.update(attributes)
        if error:
            span.status = "ERROR"
            span.error = error

        # 恢复父 Span
        if span.parent_id and span.parent_id in self._spans:
            self._current_span_id = span.parent_id
        else:
            self._current_span_id = None

        # 持久化顶层 Span
        if span.parent_id is None:
            self._persist_span(span)

    def add_event(self, span_id: str, name: str, attributes: dict = None):
        """添加 Span 事件"""
        span = self._spans.get(span_id)
        if span:
            span.events.append({
                "name": name,
                "timestamp": time.time(),
                "attributes": attributes or {},
            })

    def _persist_span(self, span: TraceSpan):
        """持久化 Span 到文件"""
        try:
            os.makedirs(os.path.dirname(self._trace_output), exist_ok=True)
            record = {
                "trace_id": span.span_id,
                "parent_id": span.parent_id,
                "name": span.name,
                "start_time": datetime.fromtimestamp(span.start_time).isoformat(),
                "duration_ms": round((span.end_time - span.start_time) * 1000, 2) if span.end_time else 0,
                "attributes": span.attributes,
                "events": span.events,
                "status": span.status,
                "error": span.error,
                "service": self.service_name,
            }
            with open(self._trace_output, "a") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to persist trace: {e}")


class TelemetryService:
    """
    遥测服务 — 统一追踪入口

    自动选择:
    - OTEL_AVAILABLE → OpenTelemetry SDK
    - 否则 → LocalTracer (JSON Lines 文件)
    """

    def __init__(self, service_name: str = "content-moderation"):
        self.service_name = service_name
        self.use_otel = OTEL_AVAILABLE

        if self.use_otel:
            self._init_otel()
            self.local_tracer = None
        else:
            self.local_tracer = LocalTracer(service_name)
            logger.info("Telemetry: using LocalTracer (file-based)")

    def _init_otel(self):
        """初始化 OpenTelemetry"""
        resource = Resource.create({
            "service.name": self.service_name,
            "service.version": "3.0.0",
        })

        provider = TracerProvider(resource=resource)

        # 控制台导出 (开发)
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

        # OTLP 导出 (Langfuse / Phoenix)
        otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if otlp_endpoint:
            otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            logger.info(f"OTLP exporter configured: {otlp_endpoint}")

        trace.set_tracer_provider(provider)
        self._tracer = trace.get_tracer(self.service_name)
        logger.info("OpenTelemetry initialized")

    @contextmanager
    def trace_agent(self, agent_name: str, content_id: str, content_type: str):
        """
        追踪 Agent 执行

        使用上下文管理器:
            with telemetry.trace_agent("text_agent", "mod_123", "text") as span:
                result = await agent.process(state)
                span.set_attribute("risk_score", result["risk_score"])
        """
        if self.use_otel and hasattr(self, "_tracer"):
            with self._tracer.start_as_current_span(
                f"agent.{agent_name}",
                attributes={
                    "agent.name": agent_name,
                    "content.id": content_id,
                    "content.type": content_type,
                },
            ) as span:
                yield span
        elif self.local_tracer:
            span_id = self.local_tracer.start_span(
                f"agent.{agent_name}",
                attributes={
                    "agent.name": agent_name,
                    "content.id": content_id,
                    "content.type": content_type,
                },
            )
            try:
                yield _LocalSpanProxy(self.local_tracer, span_id)
            finally:
                self.local_tracer.end_span(span_id)
        else:
            yield None

    def trace_llm_call(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        duration_ms: float,
        agent_name: str = "unknown",
    ):
        """追踪 LLM 调用"""
        attributes = {
            "llm.model": model,
            "llm.usage.prompt_tokens": prompt_tokens,
            "llm.usage.completion_tokens": completion_tokens,
            "llm.duration_ms": duration_ms,
            "agent.name": agent_name,
        }
        if self.use_otel and hasattr(self, "_tracer"):
            with self._tracer.start_as_current_span("llm.call", attributes=attributes) as span:
                pass
        elif self.local_tracer:
            span_id = self.local_tracer.start_span("llm.call", attributes=attributes)
            self.local_tracer.end_span(span_id)

    def trace_tool_call(
        self, tool_name: str, duration_ms: float, success: bool = True,
    ):
        """追踪 Tool 调用"""
        attributes = {
            "tool.name": tool_name,
            "tool.duration_ms": duration_ms,
            "tool.success": success,
        }
        if self.use_otel and hasattr(self, "_tracer"):
            with self._tracer.start_as_current_span("tool.call", attributes=attributes) as span:
                if not success:
                    span.set_status(Status(StatusCode.ERROR))
        elif self.local_tracer:
            span_id = self.local_tracer.start_span("tool.call", attributes=attributes)
            self.local_tracer.end_span(span_id, error=None if success else "Tool execution failed")

    def trace_workflow(self, content_id: str, content_type: str):
        """追踪整个工作流"""
        if self.use_otel and hasattr(self, "_tracer"):
            return self._tracer.start_as_current_span(
                "workflow.moderation",
                attributes={
                    "workflow.name": "content_moderation_v3",
                    "content.id": content_id,
                    "content.type": content_type,
                },
            )
        elif self.local_tracer:
            span_id = self.local_tracer.start_span(
                "workflow.moderation",
                attributes={
                    "workflow.name": "content_moderation_v3",
                    "content.id": content_id,
                    "content.type": content_type,
                },
            )
            return _LocalSpanContext(self.local_tracer, span_id)
        else:
            from contextlib import nullcontext
            return nullcontext()


class _LocalSpanProxy:
    """本地 Span 代理 (支持 set_attribute)"""
    def __init__(self, tracer: LocalTracer, span_id: str):
        self._tracer = tracer
        self._span_id = span_id

    def set_attribute(self, key: str, value: Any):
        span = self._tracer._spans.get(self._span_id)
        if span:
            span.attributes[key] = value

    def set_status(self, status):
        pass

    def add_event(self, name: str, attributes: dict = None):
        self._tracer.add_event(self._span_id, name, attributes)


class _LocalSpanContext:
    """本地 Span 上下文管理器"""
    def __init__(self, tracer: LocalTracer, span_id: str):
        self._tracer = tracer
        self._span_id = span_id

    def __enter__(self):
        return _LocalSpanProxy(self._tracer, self._span_id)

    def __exit__(self, *args):
        self._tracer.end_span(self._span_id)
        return False


# 全局实例
_telemetry: Optional[TelemetryService] = None


def get_telemetry() -> TelemetryService:
    global _telemetry
    if _telemetry is None:
        _telemetry = TelemetryService()
    return _telemetry
