"""真正的 MCP stdio 服务。stdout 只留给协议，日志由 SDK 写入 stderr。"""
from mcp.server.fastmcp import FastMCP

from .knowledge import get_place, search
from .planner import estimate_transfer, plan
from .retrieval import retrieve

mcp = FastMCP('Hong Kong Travel Tools', log_level='ERROR')


@mcp.tool()
def search_places(query: str, limit: int = 5, region: str = '全部',
                  indoor_only: bool = False, kind: str = 'all') -> dict:
    """检索本地香港官方资料摘要，返回地点、匹配依据和来源。不是实时搜索。"""
    return retrieve(query, limit, region, indoor_only, kind)


@mcp.tool()
def place_detail(place_id: str) -> dict:
    """读取指定地点的介绍、来源与参观提示。"""
    return get_place(place_id)


@mcp.tool()
def transfer_estimate(origin_id: str, destination_id: str) -> dict:
    """交通余量估算及有官方来源的港铁线路、方向、换乘和出口参考，非实时。"""
    return estimate_transfer(origin_id, destination_id)


@mcp.tool()
def plan_itinerary(days: int | None = None, region: str = '全部', interests: list[str] | None = None,
                   pace: str = '轻松', rain: bool = False, public_only: bool = False,
                   must_visit: list[str] | None = None, start_station: str = '',
                   start_date: str | None = None, end_date: str | None = None, only_selected: bool = False, excluded_places: list[str] | None = None) -> dict:
    """根据起止日期或天数、区域、兴趣与必去地点逐天安排香港草案；资料不足的日期明确列为自由活动。"""
    return plan(days, region, interests, pace, rain, public_only, must_visit, start_station, start_date, end_date, only_selected, excluded_places)


if __name__ == '__main__':
    mcp.run(transport='stdio')
