from abc import ABC, abstractmethod
import pandas as pd


class BaseDataSource(ABC):
    name: str = "base"

    @abstractmethod
    def search_stocks(self, keyword: str) -> list[dict]:
        ...

    @abstractmethod
    def get_kline(self, code: str, period: str, start_date: str, end_date: str) -> pd.DataFrame:
        ...

    @abstractmethod
    def get_realtime_quote(self, code: str) -> dict:
        ...

    def get_quotes_batch(self, codes: list[str]) -> list[dict]:
        """批量行情。默认逐个回退到 get_realtime_quote；子类可覆盖以单次往返实现。"""
        return [self.get_realtime_quote(c) for c in (codes or [])]

    @abstractmethod
    def get_index_data(self) -> list[dict]:
        ...

    def get_fund_flow_top(self, n: int = 10) -> dict:
        """主力资金流入/流出 TOP N 个股。默认返回空结构。

        return: {"date": "YYYY-MM-DD" | None,
                 "inflow":  [{code, name, main_net, price, change_pct}, ...],
                 "outflow": [{code, name, main_net, price, change_pct}, ...]}
        main_net 单位：元（亿元换算交给前端）。
        """
        return {"date": None, "inflow": [], "outflow": []}

    def get_sector_fund_flow_top(self, n: int = 5) -> dict:
        """行业板块资金流入/流出 TOP N。默认返回空结构。

        return: {"date": "YYYY-MM-DD" | None,
                 "inflow":  [{name, main_net, change_pct}, ...],
                 "outflow": [{name, main_net, change_pct}, ...]}
        """
        return {"date": None, "inflow": [], "outflow": []}

    def screen_stocks(
        self,
        sort_by: str = "amount",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 50,
        codes: list[str] | None = None,
        security_type: str = "stock",
    ) -> dict:
        """批量拉取股票行情+指标数据用于条件选股。

        返回 {"results": [标准化 dict], "total": int}。
        子类应覆盖以实现高效批量获取。
        """
        return {"results": [], "total": 0}

    def get_fundamentals(self, code: str) -> dict:
        """关键财务/估值指标。默认返回占位结构，未实现则各字段为 None。"""
        return {
            "code": code,
            "name": "",
            "price": None,
            "change_pct": None,
            "pe": None,
            "pe_ttm": None,
            "pb": None,
            "ps_ttm": None,
            "dv_ttm": None,
            "total_market_cap": None,
            "float_market_cap": None,
            "total_shares": None,
            "float_shares": None,
            "industry": "",
            "listing_date": "",
            "as_of": None,
        }


PERIOD_MAP = {
    "daily": "daily",
    "weekly": "weekly",
    "monthly": "monthly",
    "60min": "60",
    "30min": "30",
    "15min": "15",
}
