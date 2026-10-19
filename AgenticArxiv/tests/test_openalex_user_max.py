"""
Tests for openalex_tool._rule_based_parse — especially数量 (X 篇) 解析。
不依赖网络、pytest，纯 stdlib unittest。
"""
import sys
import os
import unittest
import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.openalex_tool import _rule_based_parse


def _q(s: str) -> dict:
    return _rule_based_parse(s)


class TestUserMaxResults(unittest.TestCase):
    """用户自然语言里的数量词解析"""

    def test_simple_x_pian(self):
        """'5 篇' → user_max_results=5"""
        r = _q("帮我找 5 篇 transformer 用于医学图像分割的论文")
        self.assertEqual(r["user_max_results"], 5)

    def test_x_ge(self):
        """'10 个' → user_max_results=10"""
        r = _q("给我 10 个 LLM 综述")
        self.assertEqual(r["user_max_results"], 10)

    def test_x_pian_lunwen(self):
        """'3 篇论文' → 3"""
        r = _q("最近 3 篇论文 关于 diffusion model")
        self.assertEqual(r["user_max_results"], 3)

    def test_x_pian_wenzhang(self):
        """'7 篇文章' → 7"""
        r = _q("搜索 7 篇文章 reinforcement learning robotics")
        self.assertEqual(r["user_max_results"], 7)

    def test_x_tiao(self):
        """'8 条' → 8"""
        r = _q("给我找 8 条 graph neural network 的最新研究")
        self.assertEqual(r["user_max_results"], 8)

    def test_no_number_returns_none(self):
        """不带数字 → None（不影响默认 20）"""
        r = _q("帮我搜索 transformer 用于医学图像分割的论文")
        self.assertIsNone(r["user_max_results"])

    def test_clamp_upper_bound(self):
        """超过 50 时夹紧到 50"""
        r = _q("给我 100 篇关于 AI 的论文")
        self.assertEqual(r["user_max_results"], 50)

    def test_just_want_5_papers(self):
        """典型用户句式: '只要 5 篇'"""
        r = _q("只要 5 篇")
        self.assertEqual(r["user_max_results"], 5)

    def test_year_and_count_both_work(self):
        """'2020 年的 5 篇论文' → 5 篇 + year=2020"""
        r = _q("找 2020 年的 5 篇关于 GAN 的论文")
        self.assertEqual(r["user_max_results"], 5)
        self.assertEqual(r["year_from"], 2020)


class TestYearStillWorks(unittest.TestCase):
    """回归测试：年份解析没被数量正则破坏"""

    def test_nian_5(self):
        r = _q("近 5 年 关于 GAN 的论文")
        self.assertEqual(r["year_from"], datetime.datetime.now().year - 5)

    def test_year_range(self):
        r = _q("找 2020-2023 的论文")
        self.assertEqual(r["year_from"], 2020)
        self.assertEqual(r["year_to"], 2023)

    def test_year_since(self):
        r = _q("2020 年以来的 LLM 论文")
        self.assertEqual(r["year_from"], 2020)

    def test_default_year(self):
        """没年份时默认近 5 年"""
        r = _q("transformer 用于图像分割")
        self.assertEqual(r["year_from"], datetime.datetime.now().year - 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
