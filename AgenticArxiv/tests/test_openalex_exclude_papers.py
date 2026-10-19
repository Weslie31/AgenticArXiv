"""
Tests for search_openalex_papers exclude_paper_ids logic.
通过 mock requests 来避免真实网络调用。
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestExcludePaperIds(unittest.TestCase):
    """验证 search_openalex_papers 会跳过 exclude_paper_ids 里的论文"""

    def _mock_openalex_response(self, papers):
        """构造一个 mock 的 OpenAlex 响应"""
        return {
            "results": [
                {
                    "id": f"https://openalex.org/W{i}",
                    "doi": f"https://doi.org/10.1234/test{i}",
                    "display_name": f"Test Paper {i}",
                    "publication_year": 2024,
                    "publication_date": "2024-01-01",
                    "cited_by_count": 10,
                    "type": "article",
                    "open_access": {"is_oa": True, "oa_url": None},
                    "authorships": [],
                    "abstract_inverted_index": None,
                }
                for i in range(len(papers))
            ],
            "meta": {"count": len(papers)},
        }

    def test_exclude_paper_ids_drops_papers(self):
        """传给 exclude_paper_ids 的 DOI 应该被过滤掉"""
        from tools.openalex_tool import search_openalex_papers

        # 假设 OpenAlex 返回 4 篇，doi 索引是 0,1,2,3
        mock_response = self._mock_openalex_response([0, 1, 2, 3])

        with patch("tools.openalex_tool.requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_response,
            )
            result = search_openalex_papers(
                query="test",
                max_results=4,
                exclude_paper_ids=[
                    "https://doi.org/10.1234/test1",
                    "https://doi.org/10.1234/test2",
                ],
                save_to_file=False,
            )

        # 应当只剩 2 篇（test0 和 test3）
        self.assertEqual(len(result), 2)
        returned_dois = {p.get("doi") for p in result}
        self.assertIn("https://doi.org/10.1234/test0", returned_dois)
        self.assertIn("https://doi.org/10.1234/test3", returned_dois)
        self.assertNotIn("https://doi.org/10.1234/test1", returned_dois)
        self.assertNotIn("https://doi.org/10.1234/test2", returned_dois)

    def test_exclude_paper_ids_mixed_formats(self):
        """多个 DOI 都能被正确排除（这是真实场景：store 里多个 paper 的 DOI）"""
        from tools.openalex_tool import search_openalex_papers

        # 4 篇，doi 是 test0..test3
        mock_response = self._mock_openalex_response([0, 1, 2, 3])

        with patch("tools.openalex_tool.requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_response,
            )
            # 真实场景：store.get_last_papers 返回的 id 是 DOI 完整 URL
            result = search_openalex_papers(
                query="test",
                max_results=4,
                exclude_paper_ids=[
                    "https://doi.org/10.1234/test1",
                    "https://doi.org/10.1234/test2",
                ],
                save_to_file=False,
            )

        # 应当只剩 2 篇（test0 和 test3）
        self.assertEqual(len(result), 2)
        returned_dois = {p.get("doi") for p in result}
        self.assertIn("https://doi.org/10.1234/test0", returned_dois)
        self.assertIn("https://doi.org/10.1234/test3", returned_dois)

    def test_no_exclude_returns_all(self):
        """不传 exclude_paper_ids 时全部返回"""
        from tools.openalex_tool import search_openalex_papers

        mock_response = self._mock_openalex_response([1, 2, 3])

        with patch("tools.openalex_tool.requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_response,
            )
            result = search_openalex_papers(
                query="test",
                max_results=3,
                save_to_file=False,
            )

        self.assertEqual(len(result), 3)

    def test_search_papers_nl_signature_accepts_exclude(self):
        """search_papers_nl 函数签名应支持 exclude_paper_ids"""
        import inspect
        from tools.openalex_tool import search_papers_nl

        sig = inspect.signature(search_papers_nl)
        self.assertIn("exclude_paper_ids", sig.parameters)


if __name__ == "__main__":
    unittest.main(verbosity=2)
