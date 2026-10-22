from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StringConstraints


router = APIRouter(prefix="/api/travel", tags=["旅游规划"])

# 去除首尾空白后，文字长度必须在 1～80 个字符之间。
ShortText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=80,
    ),
]


class TravelPlanRequest(BaseModel):
    # 拼错字段名时返回错误，避免悄悄忽略参数。
    model_config = ConfigDict(extra="forbid")

    destination: ShortText
    days: int = Field(strict=True, ge=1, le=14)  # 当前天数限制为1~14天
    interests: list[ShortText] = Field(
        default_factory=list,
        max_length=10, # 兴趣最多10项
    )


class DayPlan(BaseModel):
    day: int
    activities: list[str]


class Source(BaseModel):
    title: str
    url: str | None = None


class TravelPlanResponse(BaseModel):
    mode: Literal["mock"] = "mock"
    destination: str
    days: int
    interests: list[str]
    itinerary: list[DayPlan]
    sources: list[Source] = Field(default_factory=list)
    notice: str = "这是用于接口联调的示例行程，尚未接入 RAG 或 LLM。"


@router.post("/plan", response_model=TravelPlanResponse)
def create_travel_plan(request: TravelPlanRequest) -> TravelPlanResponse:
    preference = "、".join(request.interests) or "城市探索"

    itinerary = [
        DayPlan(
            day=day,
            activities=[
                f"上午：在{request.destination}游览，具体景点待生成。",
                f"下午：安排与{preference}有关的活动，具体地点待生成。",
                "晚上：安排餐饮与休息，具体地点待生成。",
            ],
        )
        for day in range(1, request.days + 1)
    ]

    return TravelPlanResponse(
        destination=request.destination,
        days=request.days,
        interests=request.interests,
        itinerary=itinerary,
    )