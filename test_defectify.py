from quickquip.llm.defectify import build_defectify_prompt


def test_build_prompt_mentions_plain_text_output() -> None:
    prompt = build_defectify_prompt(
        prompt="小蓝熊的弱智兼容性和启动速度",
        quoted_text="这也太慢了",
        quoted_sender_name="张三",
        quoted_user_id="123",
    )
    assert "不要输出 JSON" in prompt.system_prompt
    assert "笑点解析：" in prompt.system_prompt
    assert "小蓝熊的弱智兼容性和启动速度" in prompt.user_prompt
    assert "这也太慢了" in prompt.user_prompt
    assert "禁止写“障对应障”" in prompt.system_prompt
    assert "请先确保五个字都能被原输入解释" in prompt.user_prompt


if __name__ == "__main__":
    test_build_prompt_mentions_plain_text_output()
