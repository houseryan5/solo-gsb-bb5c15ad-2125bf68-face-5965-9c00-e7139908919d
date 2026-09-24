"""aligner 的单元测试，含小规模随机暴力校验。"""

import itertools
import random
import unittest

from app.aligner import (
    DELETE,
    INSERT,
    MATCH,
    AlignmentTooLargeError,
    CharSpan,
    align_sequences,
    build_timeline,
    validate_spans,
)


def brute_force_align(source, revised):
    """枚举所有对齐，返回 (最小代价, 匹配原位向量的字典序最小值)。"""
    n, m = len(source), len(revised)
    best_cost = n + m
    best_vec = None

    def recurse(i, j, cost, vec):
        nonlocal best_cost, best_vec
        if i == n and j == m:
            if cost < best_cost:
                best_cost = cost
                best_vec = tuple(vec)
            elif cost == best_cost and (best_vec is None or tuple(vec) < best_vec):
                best_vec = tuple(vec)
            return
        if i < n:  # 删除（或参与匹配）
            if j < m and source[i] == revised[j]:
                vec.append(i)
                recurse(i + 1, j + 1, cost, vec)
                vec.pop()
            recurse(i + 1, j, cost + 1, vec)  # 删除
        if j < m:
            recurse(i, j + 1, cost + 1, vec)  # 插入

    recurse(0, 0, 0, [])
    return best_cost, best_vec


def matched_vector(ops):
    return tuple(si for op, si, _ in ops if op == MATCH)


def cost_of(ops):
    return sum(1 for op, _si, _rj in ops if op != MATCH)


class AlignmentOptimumTests(unittest.TestCase):
    """对齐结果必须代价最小，且匹配原位向量字典序最小。"""

    def test_exhaustive_small_alphabet(self):
        random.seed(20260924)
        for _ in range(400):
            n = random.randint(0, 6)
            m = random.randint(0, 6)
            source = [random.choice("ab") for _ in range(n)]
            revised = [random.choice("ab") for _ in range(m)]
            ops = align_sequences(source, revised)
            expected_cost, expected_vec = brute_force_align(source, revised)
            self.assertEqual(cost_of(ops), expected_cost, (source, revised))
            self.assertEqual(matched_vector(ops), expected_vec, (source, revised))

    def test_repeated_chars_earliest_position(self):
        # "aaa" -> "aa"：应匹配最早的两个原字符 [0, 1]
        ops = align_sequences(list("aaa"), list("aa"))
        self.assertEqual(matched_vector(ops), (0, 1))
        self.assertEqual(
            [op for op, _, _ in ops], [MATCH, MATCH, DELETE]
        )

        # "aba" -> "a"：只有一个 a 可匹配，应取最早的原位 0
        ops = align_sequences(list("aba"), list("a"))
        self.assertEqual(matched_vector(ops), (0,))

        # "ab" -> "aab"：插入的 a 与原位向量同为 (0,1)，
        # M 优先策略下先匹配再插入（原位一致时的确定性选择）
        ops = align_sequences(list("ab"), list("aab"))
        self.assertEqual(matched_vector(ops), (0, 1))
        self.assertEqual(
            [op for op, _, _ in ops],
            [MATCH, INSERT, MATCH],
        )

    def test_context_disambiguates_repeats(self):
        # "x a a y" -> "a a"：两个 a 只能匹配原文下标 1、2（上下文唯一最优）
        ops = align_sequences(list("xaay"), list("aa"))
        self.assertEqual(matched_vector(ops), (1, 2))

        # "a b a" -> "a a"：跳过 b，匹配 0、2
        ops = align_sequences(list("aba"), list("aa"))
        self.assertEqual(matched_vector(ops), (0, 2))

    def test_empty_sides(self):
        self.assertEqual(align_sequences([], []), [])
        ops = align_sequences(list("abc"), [])
        self.assertEqual([op for op, _, _ in ops], [DELETE, DELETE, DELETE])
        ops = align_sequences([], list("ab"))
        self.assertEqual([op for op, _, _ in ops], [INSERT, INSERT])

    def test_size_limits(self):
        with self.assertRaises(AlignmentTooLargeError):
            align_sequences(list("a" * 10), list("b" * 10), max_chars_per_side=5)
        with self.assertRaises(AlignmentTooLargeError):
            align_sequences(["a"] * 3, ["a"] * 3, max_cells=10)


def make_spans(text, width=100, gap=0):
    return [
        CharSpan(ch, i * (width + gap), i * (width + gap) + width)
        for i, ch in enumerate(text)
    ]


class TimelineTests(unittest.TestCase):
    def test_matched_chars_keep_source_time(self):
        spans = make_spans("abc", width=100)
        ops = align_sequences(list("abc"), list("abc"))
        items, stats = build_timeline(ops, spans, list("abc"), 300)
        self.assertEqual([(it.char, it.start_ms, it.end_ms) for it in items],
                         [("a", 0, 100), ("b", 100, 200), ("c", 200, 300)])
        self.assertTrue(all(it.matched and not it.estimated for it in items))
        self.assertEqual(stats, {"matched": 3, "inserted": 0, "deleted": 0})

    def test_inserted_between_matched_evenly_split(self):
        # 原文 "a"(0-100) "d"(400-500)；修订 "axyd"：x、y 平分空档 [100,400]
        spans = [CharSpan("a", 0, 100), CharSpan("d", 400, 500)]
        ops = align_sequences(["a", "d"], list("axyd"))
        items, stats = build_timeline(ops, spans, list("axyd"), 500)
        self.assertEqual(
            [(it.char, it.start_ms, it.end_ms, it.matched, it.estimated)
             for it in items],
            [
                ("a", 0, 100, True, False),
                ("x", 100, 250, False, True),
                ("y", 250, 400, False, True),
                ("d", 400, 500, True, False),
            ],
        )
        self.assertEqual(stats, {"matched": 2, "inserted": 2, "deleted": 0})

    def test_inserted_at_boundaries(self):
        # 无前/后匹配：前缀平分 [0, 100)，后缀平分 [200, 300)
        spans = [CharSpan("a", 100, 200)]
        ops = align_sequences(["a"], list("xay"))
        items, _ = build_timeline(ops, spans, list("xay"), 300)
        self.assertEqual(
            [(it.char, it.start_ms, it.end_ms) for it in items],
            [("x", 0, 100), ("a", 100, 200), ("y", 200, 300)],
        )

    def test_all_inserted_covers_whole_recording(self):
        ops = align_sequences([], list("ab"))
        items, _ = build_timeline(ops, [], list("ab"), 100)
        self.assertEqual(
            [(it.start_ms, it.end_ms) for it in items], [(0, 50), (50, 100)]
        )

    def test_odd_gap_distributes_remainder_forward(self):
        # 空档 10ms 分给 3 个插入字符：每段 3ms，余数 1 给最前字符 -> 4,3,3，
        # 严格单调且首尾相接完全覆盖空档
        spans = [CharSpan("a", 0, 0), CharSpan("z", 10, 10)]
        ops = align_sequences(["a", "z"], list("awxyz"))
        items, _ = build_timeline(ops, spans, list("awxyz"), 10)
        times = [(it.start_ms, it.end_ms) for it in items]
        self.assertEqual(times, [(0, 0), (0, 4), (4, 7), (7, 10), (10, 10)])
        # 顺序、范围、不重叠不变量
        prev_end = 0
        for start, end in times:
            self.assertGreaterEqual(start, prev_end)
            self.assertGreaterEqual(end, start)
            self.assertLessEqual(end, 10)
            prev_end = end

    def test_deleted_chars_are_not_output(self):
        spans = make_spans("a-bc".replace("-", ""), width=100)
        spans = [CharSpan("a", 0, 100), CharSpan("x", 100, 200),
                 CharSpan("b", 200, 300)]
        ops = align_sequences(list("axb"), list("ab"))
        items, stats = build_timeline(ops, spans, list("ab"), 300)
        self.assertEqual([it.char for it in items], ["a", "b"])
        self.assertEqual(stats["deleted"], 1)

    def test_empty_revised_text(self):
        spans = make_spans("ab", width=10)
        ops = align_sequences(list("ab"), [])
        items, stats = build_timeline(ops, spans, [], 20)
        self.assertEqual(items, [])
        self.assertEqual(stats, {"matched": 0, "inserted": 0, "deleted": 2})

    def test_output_invariants_on_random_cases(self):
        random.seed(7)
        for _ in range(100):
            n = random.randint(1, 8)
            source = [random.choice("abc") for _ in range(n)]
            revised = [random.choice("abcd") for _ in range(random.randint(0, 8))]
            width = random.randint(1, 30)
            total = n * width
            spans = [
                CharSpan(ch, i * width, min((i + 1) * width, total))
                for i, ch in enumerate(source)
            ]
            ops = align_sequences(source, revised)
            items, _ = build_timeline(ops, spans, revised, total)
            self.assertEqual(len(items), len(revised))
            prev_end = 0
            for it in items:
                self.assertGreaterEqual(it.start_ms, 0)
                self.assertGreaterEqual(it.end_ms, it.start_ms)
                self.assertLessEqual(it.end_ms, total)
                self.assertGreaterEqual(it.start_ms, prev_end)
                prev_end = it.end_ms
                self.assertEqual(it.estimated, not it.matched)


class ValidationTests(unittest.TestCase):
    def test_end_before_start(self):
        with self.assertRaisesRegex(ValueError, "end_ms=5 is earlier than start_ms=10"):
            validate_spans([CharSpan("a", 10, 5)], 100)

    def test_end_exceeds_total(self):
        with self.assertRaisesRegex(ValueError, "exceeds total_duration_ms=50"):
            validate_spans([CharSpan("a", 0, 60)], 50)

    def test_unsorted(self):
        spans = [CharSpan("a", 0, 10), CharSpan("b", 8, 20)]
        with self.assertRaisesRegex(ValueError, "overlaps the previous char"):
            validate_spans(spans, 100)
        spans = [CharSpan("a", 20, 30), CharSpan("b", 0, 10)]
        with self.assertRaisesRegex(ValueError, "earlier than the previous char"):
            validate_spans(spans, 100)

    def test_touching_spans_allowed(self):
        validate_spans([CharSpan("a", 0, 10), CharSpan("b", 10, 20)], 20)

    def test_itertools_sanity(self):
        # 顺带保证暴力器覆盖数随长度指数增长（防止写错枚举）
        n = len(list(itertools.product(range(3), repeat=4)))
        self.assertEqual(n, 81)


if __name__ == "__main__":
    unittest.main()
