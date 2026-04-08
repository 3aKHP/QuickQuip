from quickquip.llm.defectify import build_defectify_prompt


def test_build_prompt_basic_structure() -> None:
    prompt = build_defectify_prompt(
        prompt="小蓝熊的弱智兼容性和启动速度",
        quoted_text="这也太慢了",
        quoted_sender_name="张三",
        quoted_user_id="123",
    )
    assert "槽1" in prompt.system_prompt
    assert "槽2" in prompt.system_prompt
    assert "笑点解析：" in prompt.system_prompt
    assert "禁止输出 JSON" in prompt.system_prompt
    assert "小蓝熊的弱智兼容性和启动速度" in prompt.user_prompt
    assert "这也太慢了" in prompt.user_prompt


def test_build_prompt_no_quoted() -> None:
    prompt = build_defectify_prompt(prompt="测试内容")
    assert "测试内容" in prompt.user_prompt
    assert "引用" not in prompt.user_prompt


def test_build_prompt_image_only() -> None:
    prompt = build_defectify_prompt(
        prompt="",
        image_urls=["http://example.com/img.jpg"],
    )
    assert "图片" in prompt.user_prompt
    assert "1 张" in prompt.user_prompt


if __name__ == "__main__":
    test_build_prompt_basic_structure()
    test_build_prompt_no_quoted()
    test_build_prompt_image_only()
    print("all pass")
