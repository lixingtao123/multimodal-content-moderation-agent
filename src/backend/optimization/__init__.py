"""
优化模块 — AnnotationAgent 标注校验 + 反馈闭环 + OptimizationAgent 智能优化
"""
from .prompt_optimizer import (
    PromptRegistry,
    PromptVersion,
    DspyStyleOptimizer,
    FeedbackLoop,
    get_prompt_registry,
    get_optimizer,
    get_feedback_loop,
)
from .annotation_agent import (
    AnnotationAgent,
    AnnotationInput,
    AnnotationResult,
    get_annotation_agent,
)
from .annotation_queue import (
    AnnotationConsumer,
    enqueue_annotation,
    get_annotation_consumer,
    get_annotation_stats,
    get_annotation_buffer,
    get_annotation_result,
    trigger_manual_optimization,
    get_optimization_reports,
)
from .optimization_agent import (
    OptimizationAgent,
    OptimizationAction,
    get_optimization_agent,
)
