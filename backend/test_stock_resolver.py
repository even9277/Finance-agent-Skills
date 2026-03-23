"""
测试 stock_resolver 三层解析功能
用于验证 P1 修复后的股票名称/代码解析效果
"""
import asyncio
import sys
from pathlib import Path

# 添加路径
_BACKEND_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _BACKEND_ROOT.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.services.stock_resolver import resolve_stock

# 测试用例
test_cases = [
    # (输入, 预期company_name, 预期stock_code)
    ("分析贵州茅台", "贵州茅台", "sh.600519"),
    ("帮我看看比亚迪最近走势", "比亚迪", "sz.002594"),
    ("600519", None, "sh.600519"),  # 纯代码
    ("宁德时代的基本面如何", "宁德时代", "sz.300750"),
    ("研究一下光伏龙头隆基绿能", "隆基绿能", "sh.601012"),
    ("分析一下贵州茅台(600519)", "贵州茅台", "sh.600519"),
]


async def main():
    print("=" * 60)
    print("P1 股票名称/代码解析功能测试")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    for i, (query, expect_name, expect_code) in enumerate(test_cases, 1):
        print(f"\n测试 {i}: {query}")
        print("-" * 60)
        
        try:
            company_name, stock_code = await resolve_stock(query)
            
            # 显示结果
            print(f"  解析结果: company='{company_name}', code='{stock_code}'")
            print(f"  预期结果: company='{expect_name}', code='{expect_code}'")
            
            # 判断是否通过（name 可以为 None 或匹配；code 必须匹配）
            name_ok = (expect_name is None) or (company_name and expect_name in company_name) or (company_name == expect_name)
            code_ok = stock_code == expect_code
            
            if name_ok and code_ok:
                print("  ✅ 通过")
                passed += 1
            else:
                print(f"  ❌ 失败 - name_ok={name_ok}, code_ok={code_ok}")
                failed += 1
                
        except Exception as exc:
            print(f"  ❌ 异常: {exc}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
