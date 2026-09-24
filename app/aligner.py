"""全局最小编辑代价对齐与逐字时间轴生成。

对齐模型（等价于以"相同字符匹配代价为 0、插入/删除代价为 1"的
Needleman-Wunsch / LCS 全局对齐）：

* 识别原文中的字符被删除（人工删字）-> DELETE，不输出；
* 修订文本中新增的字符                 -> INSERT，时间按相邻空档均匀推算；
* 修订字符与原文字符相同               -> MATCH，沿用原字符的起止时间。

重复字符的匹配位置由全局最优解决定（结合上下文），并且在所有最优解中
保证"修订文本依次匹配到的原文字符位置"字典序最小，即同分优先较早的
原位置。实现方式：后缀 DP + 从左到右贪心重建（能匹配就匹配）。
"""

from array import array
from dataclasses import dataclass
from typing import List, Sequence, Tuple

MATCH = 0
INSERT = 1
DELETE = 2


class AlignmentTooLargeError(ValueError):
    """输入规模超过配置上限。"""


@dataclass(frozen=True)
class CharSpan:
    """一个识别字符及其毫秒级起止时间。"""

    char: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class TimelineChar:
    """修订文本中一个字符的时间轴条目。"""

    char: str
    start_ms: int
    end_ms: int
    matched: bool
    estimated: bool


def align_sequences(
    source: Sequence[str],
    revised: Sequence[str],
    max_chars_per_side: int = 8000,
    max_cells: int = 10_000_000,
) -> List[Tuple[int, int, int]]:
    """对识别原文与人工修订文本做全局最小编辑代价对齐。

    返回操作序列 ``[(op, source_index, revised_index), ...]``，按对齐顺序
    排列；不涉及的一侧下标记为 -1。

    规模约束：单边字符数不超过 ``max_chars_per_side``，且 DP 单元数
    ``(n+1)*(m+1)`` 不超过 ``max_cells``，否则抛出
    :class:`AlignmentTooLargeError`。
    """
    n, m = len(source), len(revised)

    if n > max_chars_per_side or m > max_chars_per_side:
        raise AlignmentTooLargeError(
            "input too long: each side may contain at most "
            f"{max_chars_per_side} characters, got {n} and {m}"
        )
    if (n + 1) * (m + 1) > max_cells:
        raise AlignmentTooLargeError(
            "alignment too large: (recognized+1)*(revised+1) = "
            f"{(n + 1) * (m + 1)} exceeds the configured limit {max_cells}; "
            "raise MAX_ALIGNMENT_CELLS or shorten the input"
        )

    # 代价最大为 n + m；单边上限 8000 时 < 32767，可存入有符号 16 位整数。
    if n + m > 32767:  # 兜底，正常配置下不会触发
        raise AlignmentTooLargeError("combined input length exceeds 32767 characters")

    # 后缀 DP：dp[i][j] = 对齐 source[i:] 与 revised[j:] 的最小代价。
    rows: List[array] = [None] * (n + 1)  # type: ignore[list-item]
    rows[n] = array("h", (m - j for j in range(m + 1)))

    for i in range(n - 1, -1, -1):
        cur = array("h", [0]) * (m + 1)
        cur[m] = n - i
        nxt = rows[i + 1]
        si = source[i]
        for j in range(m - 1, -1, -1):
            delete_cost = nxt[j] + 1
            insert_cost = cur[j + 1] + 1
            best = delete_cost if delete_cost <= insert_cost else insert_cost
            if si == revised[j]:
                match_cost = nxt[j + 1]
                if match_cost < best:
                    best = match_cost
            cur[j] = best
        rows[i] = cur

    # 贪心重建（M -> I -> D）：在总代价最优的前提下，让修订文本依次
    # 匹配到的原文字符下标字典序最小，即同分优先较早的原位置；
    # 原位置相同时优先匹配修订文本中较早的字符。
    ops: List[Tuple[int, int, int]] = []
    i = j = 0
    while i < n or j < m:
        if (
            i < n
            and j < m
            and source[i] == revised[j]
            and rows[i + 1][j + 1] == rows[i][j]
        ):
            ops.append((MATCH, i, j))
            i += 1
            j += 1
        elif j < m and (i >= n or rows[i][j + 1] + 1 == rows[i][j]):
            ops.append((INSERT, -1, j))
            j += 1
        else:
            ops.append((DELETE, i, -1))
            i += 1

    return ops


def _fill_inserted(
    items: List[TimelineChar],
    revised: Sequence[str],
    lo: int,
    hi: int,
    gap_start: int,
    gap_end: int,
) -> None:
    """把修订文本下标 [lo, hi) 的新增字符均匀分布到 [gap_start, gap_end]。

    空档被切成 k 段且首尾相接、完全覆盖空档；有余数时把多出的毫秒
    依次分给靠前的字符，保证时间戳单调、不越界、为整数。
    """
    k = hi - lo
    width = gap_end - gap_start
    step, remainder = divmod(width, k)
    for t in range(1, k + 1):
        start_ms = gap_start + (t - 1) * step + min(t - 1, remainder)
        end_ms = gap_start + t * step + min(t, remainder)
        idx = lo + t - 1
        items[idx] = TimelineChar(
            char=revised[idx],
            start_ms=start_ms,
            end_ms=end_ms,
            matched=False,
            estimated=True,
        )


def build_timeline(
    ops: Sequence[Tuple[int, int, int]],
    spans: Sequence[CharSpan],
    revised: Sequence[str],
    total_duration_ms: int,
) -> Tuple[List[TimelineChar], dict]:
    """根据对齐结果生成修订文本的逐字时间轴。

    * 匹配字符沿用识别原文的起止毫秒，``matched=true, estimated=false``；
    * 新增字符在"前一已匹配字符结尾 / 录音起点 0"与
      "后一已匹配字符开头 / 录音结尾 total_duration_ms"之间均匀分配，
      ``matched=false, estimated=true``；
    * 删除字符不输出。

    返回 ``(条目列表, 统计信息)``，条目顺序与修订文本字符顺序一致。
    """
    items: List[TimelineChar] = [None] * len(revised)  # type: ignore[list-item]
    matched_pairs = [(si, rj) for op, si, rj in ops if op == MATCH]
    deleted = sum(1 for op, _si, _rj in ops if op == DELETE)

    prev_end_ms = 0
    prev_rev_idx = -1

    for src_idx, rev_idx in matched_pairs:
        # 当前匹配字符之前、上一匹配字符之后的新增字符。
        if rev_idx > prev_rev_idx + 1:
            _fill_inserted(
                items,
                revised,
                prev_rev_idx + 1,
                rev_idx,
                prev_end_ms,
                spans[src_idx].start_ms,
            )
        span = spans[src_idx]
        items[rev_idx] = TimelineChar(
            char=revised[rev_idx],
            start_ms=span.start_ms,
            end_ms=span.end_ms,
            matched=True,
            estimated=False,
        )
        prev_end_ms = span.end_ms
        prev_rev_idx = rev_idx

    # 最后一个匹配字符之后（或完全没有匹配时）的新增字符，延伸到录音结尾。
    if len(revised) > prev_rev_idx + 1:
        _fill_inserted(
            items,
            revised,
            prev_rev_idx + 1,
            len(revised),
            prev_end_ms,
            total_duration_ms,
        )

    stats = {
        "matched": len(matched_pairs),
        "inserted": len(revised) - len(matched_pairs),
        "deleted": deleted,
    }
    return items, stats


def validate_spans(spans: Sequence[CharSpan], total_duration_ms: int) -> None:
    """校验识别字符的时间信息，无效时抛出带明确说明的 ValueError。"""
    prev_start = 0
    prev_end = 0
    for idx, span in enumerate(spans):
        if span.end_ms < span.start_ms:
            raise ValueError(
                f"chars[{idx}] ('{span.char}') is invalid: end_ms="
                f"{span.end_ms} is earlier than start_ms={span.start_ms}"
            )
        if span.end_ms > total_duration_ms:
            raise ValueError(
                f"chars[{idx}] ('{span.char}') is invalid: end_ms="
                f"{span.end_ms} exceeds total_duration_ms={total_duration_ms}"
            )
        if idx > 0:
            if span.start_ms < prev_start:
                raise ValueError(
                    f"chars[{idx}] ('{span.char}') is invalid: start_ms="
                    f"{span.start_ms} is earlier than the previous char's "
                    f"start_ms={prev_start}; input must be time-sorted"
                )
            if span.start_ms < prev_end:
                raise ValueError(
                    f"chars[{idx}] ('{span.char}') is invalid: start_ms="
                    f"{span.start_ms} overlaps the previous char which ends "
                    f"at {prev_end}; per-character spans must not overlap"
                )
        prev_start = span.start_ms
        prev_end = span.end_ms
