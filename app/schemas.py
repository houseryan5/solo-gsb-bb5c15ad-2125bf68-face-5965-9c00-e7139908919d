"""请求 / 响应 Pydantic 模型。"""

from typing import List

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RecognizedCharIn(BaseModel):
    """单个识别字符（含毫秒级起止时间）。"""

    model_config = ConfigDict(extra="ignore")

    char: str = Field(..., description="单个 Unicode 字符（空格、标点也算一个字符）")
    start_ms: int = Field(..., ge=0, description="起始毫秒，相对录音开头")
    end_ms: int = Field(..., ge=0, description="结束毫秒，相对录音开头")

    @field_validator("char")
    @classmethod
    def _exactly_one_character(cls, value: str) -> str:
        if len(value) != 1:
            raise ValueError(
                f"char must contain exactly one Unicode character, got {len(value)}: {value!r}"
            )
        return value


class AlignRequest(BaseModel):
    """POST /align 的请求体。"""

    chars: List[RecognizedCharIn] = Field(
        ..., description="按开始时间升序排列的识别字符"
    )
    total_duration_ms: int = Field(
        ..., ge=0, description="录音总时长（毫秒）"
    )
    revised_text: str = Field(..., description="人工修订后的完整文本")


class TimelineCharOut(BaseModel):
    """修订文本中单个字符的校时结果。"""

    char: str
    start_ms: int = Field(..., description="起始毫秒")
    end_ms: int = Field(..., description="结束毫秒")
    matched: bool = Field(
        ..., description="true=匹配到识别原文并沿用其时间；false=新增字符"
    )
    estimated: bool = Field(
        ..., description="true=时间由相邻空档均匀推算；false=直接采用识别时间"
    )


class AlignmentStats(BaseModel):
    matched: int = Field(..., description="匹配成功的字符数")
    inserted: int = Field(..., description="修订文本中新增的字符数")
    deleted: int = Field(..., description="识别原文中被删除、未输出的字符数")


class AlignResponse(BaseModel):
    total_duration_ms: int
    recognized_count: int
    revised_count: int
    items: List[TimelineCharOut]
    stats: AlignmentStats


class HealthResponse(BaseModel):
    status: str
    service: str
