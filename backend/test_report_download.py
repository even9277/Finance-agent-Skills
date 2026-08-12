"""报告下载响应头的回归测试。"""

import unittest

from backend.routers.report import _build_content_disposition


class ReportDownloadHeaderTests(unittest.TestCase):
    """验证下载文件名兼容 HTTP 头编码与非 ASCII 字符。"""

    def test_chinese_filename_uses_rfc5987_encoding(self) -> None:
        """中文文件名应提供 UTF-8 扩展参数及可编码的 ASCII 回退名。"""
        header = _build_content_disposition("贵州茅台_20260812.md")

        header.encode("latin-1")
        self.assertIn("filename*=UTF-8''%E8%B4%B5%E5%B7%9E", header)
        self.assertNotIn("贵州茅台", header)

    def test_filename_removes_header_line_breaks(self) -> None:
        """文件名中的换行不得形成额外响应头。"""
        header = _build_content_disposition("report\r\nInjected.md")

        self.assertNotIn("\r", header)
        self.assertNotIn("\n", header)
        self.assertIn("reportInjected.md", header)


if __name__ == "__main__":
    unittest.main()
