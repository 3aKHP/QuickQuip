from __future__ import annotations

from quickquip.llm.image_preprocessor import ImageDescription
from quickquip.llm.image_routing import (
    match_image_descriptions,
    plan_non_vision_images,
)


def test_plan_labels_direct_quoted_and_forward_images():
    plan = plan_non_vision_images(
        image_urls=["direct.png"],
        quoted_image_urls=["quoted.png"],
        forward_image_urls=["forward.png"],
        recent_messages=None,
        include_recent_images=False,
        max_trigger_context_messages=20,
    )

    assert [(item.url, item.context_label) for item in plan.candidates] == [
        ("direct.png", "当前消息图片 1"),
        ("quoted.png", "引用消息图片 1"),
        ("forward.png", "转发消息图片 1"),
    ]


def test_plan_fills_remaining_budget_with_newest_recent_images():
    recent_messages = [
        {
            "text": str(index),
            "image_urls": [f"recent-{index}.png"],
        }
        for index in range(6)
    ]

    plan = plan_non_vision_images(
        image_urls=["direct.png"],
        quoted_image_urls=[],
        forward_image_urls=[],
        recent_messages=recent_messages,
        include_recent_images=True,
        max_trigger_context_messages=20,
    )

    assert [item.url for item in plan.candidates] == [
        "direct.png",
        "recent-5.png",
        "recent-4.png",
        "recent-3.png",
        "recent-2.png",
    ]


def test_plan_rejects_too_many_primary_images():
    plan = plan_non_vision_images(
        image_urls=[f"{index}.png" for index in range(6)],
        quoted_image_urls=[],
        forward_image_urls=[],
        recent_messages=None,
        include_recent_images=False,
        max_trigger_context_messages=20,
    )

    assert plan.candidates == []
    assert plan.error_reply.startswith("一次最多识别 5 张图片")


def test_match_descriptions_preserves_labels_and_reports_failures():
    plan = plan_non_vision_images(
        image_urls=["ok.png", "failed.png"],
        quoted_image_urls=[],
        forward_image_urls=[],
        recent_messages=None,
        include_recent_images=False,
        max_trigger_context_messages=20,
    )
    raw_descriptions = [
        ImageDescription(
            source_url="ok.png",
            text_description="识别成功",
            success=True,
        ),
        ImageDescription(
            source_url="failed.png",
            text_description="",
            success=False,
            error="timeout",
        ),
    ]

    matched = match_image_descriptions(plan.candidates, raw_descriptions)

    assert matched.descriptions[0].context_label == "当前消息图片 1"
    assert matched.failed_urls == ["failed.png"]
