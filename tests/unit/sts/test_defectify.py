from __future__ import annotations

from quickquip.sts.formulas.defectify.prompting import build_defectify_prompt


def test_build_prompt_preserves_input_and_quote():
    prompt = build_defectify_prompt(
        prompt="小蓝熊的弱智兼容性和启动速度",
        quoted_text="这也太慢了",
        quoted_sender_name="张三",
        quoted_user_id="123",
    )
    assert "小蓝熊的弱智兼容性和启动速度" in prompt.user_prompt
    assert "这也太慢了" in prompt.user_prompt


def test_build_prompt_without_quote():
    prompt = build_defectify_prompt(prompt="测试内容")
    assert "测试内容" in prompt.user_prompt
    assert "引用" not in prompt.user_prompt


def test_build_prompt_image_only():
    prompt = build_defectify_prompt(
        prompt="",
        image_urls=["http://example.com/img.jpg"],
    )
    assert "图片" in prompt.user_prompt
    assert "1 张" in prompt.user_prompt
