"""FastAPI 应用：采访逐字稿校时 API。"""

import os
from typing import List

from fastapi import FastAPI, HTTPException

from .aligner import (
    AlignmentTooLargeError,
    CharSpan,
    align_sequences,
    build_timeline,
    validate_spans,
)
from .schemas import (
    AlignRequest,
    AlignResponse,
    AlignmentStats,
    HealthResponse,
    TimelineCharOut,
)

SERVICE_NAME = "transcript-align-api"

MAX_CHARS_PER_SIDE = int(os.getenv("MAX_CHARS_PER_SIDE", "8000"))
MAX_ALIGNMENT_CELLS = int(os.getenv("MAX_ALIGNMENT_CELLS", "10000000"))

app = FastAPI(
    title="采访逐字稿校时 API",
    description=(
        "对按时间排序的识别字符与人工修订文本做全局最小编辑代价对齐，"
        "为修订文本生成逐字毫秒时间轴。"
    ),
    version="1.0.0",
)


@app.get("/", response_model=HealthResponse, tags=["health"])
def root() -> HealthResponse:
    return HealthResponse(status="ok", service=SERVICE_NAME)


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=SERVICE_NAME)


@app.post(
    "/align",
    response_model=AlignResponse,
    tags=["align"],
    summary="为人工修订文本生成逐字时间轴",
)
def align_text(request: AlignRequest) -> AlignResponse:
    spans: List[CharSpan] = [
        CharSpan(char=c.char, start_ms=c.start_ms, end_ms=c.end_ms)
        for c in request.chars
    ]

    try:
        validate_spans(spans, request.total_duration_ms)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    source = [span.char for span in spans]
    revised = list(request.revised_text)

    try:
        ops = align_sequences(
            source,
            revised,
            max_chars_per_side=MAX_CHARS_PER_SIDE,
            max_cells=MAX_ALIGNMENT_CELLS,
        )
    except AlignmentTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    items, stats = build_timeline(
        ops, spans, revised, request.total_duration_ms
    )

    return AlignResponse(
        total_duration_ms=request.total_duration_ms,
        recognized_count=len(spans),
        revised_count=len(revised),
        items=[
            TimelineCharOut(
                char=item.char,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                matched=item.matched,
                estimated=item.estimated,
            )
            for item in items
        ],
        stats=AlignmentStats(**stats),
    )
