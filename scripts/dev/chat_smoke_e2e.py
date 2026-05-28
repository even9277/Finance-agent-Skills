from __future__ import annotations

CASES = [
    "贵州茅台今天怎么样",
    "ETF 和 LOF 有什么区别",
    "平安现在能买吗",
    "华安黄金 ETF 和博时黄金 ETF 哪个适合我",
]


def main() -> None:
    for idx, case in enumerate(CASES, start=1):
        print(f"{idx}. {case}")
    print("Run these against the local chat endpoint after enabling chat skill flags.")


if __name__ == "__main__":
    main()
