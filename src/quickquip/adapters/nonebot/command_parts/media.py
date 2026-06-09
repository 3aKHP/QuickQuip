from __future__ import annotations

from io import BytesIO

from quickquip.adapters.nonebot.command_parts.common import _DRAW_QUALITY_RE, _DRAW_SIZE_RE, _extract_image_urls, _format_music_models, _format_tts_models, _format_voice_groups, _parse_music_args, _parse_tts_args, _resolve_message_content, _safe_shlex_split, _send_lyrics_forward, _strip_command_name
from quickquip.app.message_pipeline import rate_limiter
from quickquip.generation.audio import generate_audio, list_available_voices
from quickquip.generation.errors import GenerationProviderError
from quickquip.generation.image import ImageInput, download_image, generate_image
from quickquip.generation.music import generate_lyrics, generate_music
from quickquip.generation.service import generation_service


def register_media_commands(on_command, Message, MessageSegment) -> None:
    draw_cmd = on_command("draw", priority=10, block=True)

    @draw_cmd.handle()
    async def _(bot, event):
        group_id = getattr(event, "group_id", None)
        if not rate_limiter.allow("image_gen", event.user_id, group_id=group_id):
            await draw_cmd.finish("图片生成过于频繁，请稍后再试")
        generation_config = generation_service.get_config()
        if generation_config.load_error:
            await draw_cmd.finish(f"图片生成配置错误：{generation_config.load_error}")
        image_generation = generation_config.image
        if not image_generation.enabled:
            await draw_cmd.finish("图片生成功能未启用")
        if not image_generation.models:
            await draw_cmd.finish("图片生成模型未配置")
        text = str(event.get_message()).strip()
        prompt = _strip_command_name(text, "draw").strip()
        first_word = prompt.split()[0] if prompt else ""
        resolved_model = None
        if first_word:
            resolved_model = image_generation.resolve_model(first_word)
        if resolved_model is not None:
            prompt = prompt[len(first_word):].strip()
        else:
            resolved_model = image_generation.resolve_model()
        if resolved_model is None:
            await draw_cmd.finish("图片生成默认模型未配置")
        model_config = resolved_model.model_config
        provider = resolved_model.provider
        size_m = _DRAW_SIZE_RE.search(prompt)
        quality_m = _DRAW_QUALITY_RE.search(prompt)
        size_override = size_m.group(1) if size_m else None
        quality_override = quality_m.group(1) if quality_m else None
        if size_m:
            prompt = _DRAW_SIZE_RE.sub("", prompt).strip()
        if quality_m:
            prompt = _DRAW_QUALITY_RE.sub("", prompt).strip()
        # Collect text and images from replied-to message (if any)
        reply = getattr(event, "reply", None)
        reply_text, reply_urls = "", []
        if reply and reply.message:
            reply_text, reply_urls = await _resolve_message_content(bot, reply.message)
        # Own message: text already in prompt, collect images only
        own_urls = _extract_image_urls(event.get_message())
        # Merge: reply text prefixed before user's own prompt
        full_prompt = "\n".join(filter(None, [reply_text, prompt])).strip()
        if not full_prompt and not reply_urls and not own_urls:
            model_ids = list(image_generation.models)
            hint = "用法：/draw [模型] [--size 宽x高] [--quality 值] <描述>"
            if len(model_ids) > 1:
                await draw_cmd.finish(
                    f"{hint}\n可用模型：{'、'.join(model_ids)}（默认：{image_generation.default_model}）"
                )
            await draw_cmd.finish(hint)
        if full_prompt and any(w in full_prompt.lower() for w in image_generation.prompt_blocklist):
            await draw_cmd.finish("提示词包含不允许的内容，请修改后重试")
        await draw_cmd.send("正在生成图片，请稍候…")
        input_images: list[ImageInput] = []
        for url in reply_urls + own_urls:
            try:
                input_images.append(await download_image(url))
            except Exception:
                pass
        try:
            image_b64 = await generate_image(
                model_config, provider, full_prompt,
                input_images=input_images or None,
                size=size_override, quality=quality_override,
            )
        except GenerationProviderError as exc:
            await draw_cmd.finish(f"图片生成失败：{exc}")
        except Exception as exc:
            await draw_cmd.finish(f"图片生成异常：{type(exc).__name__}: {exc}")
        await draw_cmd.finish(Message([MessageSegment.image(f"base64://{image_b64}")]))

    tts_cmd = on_command("tts", priority=10, block=True)

    @tts_cmd.handle()
    async def _(bot, event):
        group_id = getattr(event, "group_id", None)
        generation_config = generation_service.get_config()
        if generation_config.load_error:
            await tts_cmd.finish(f"语音生成配置错误：{generation_config.load_error}")
        audio_generation = generation_config.audio
        if not audio_generation.enabled:
            await tts_cmd.finish("语音生成功能未启用")
        if not audio_generation.models:
            await tts_cmd.finish("语音生成模型未配置")

        text = str(event.get_message()).strip()
        raw_args = _strip_command_name(text, "tts").strip()
        if raw_args == "models":
            await tts_cmd.finish(_format_tts_models(audio_generation))

        if raw_args.startswith("voices"):
            pieces = _safe_shlex_split(raw_args)
            maybe_model = pieces[1] if len(pieces) > 1 and pieces[1] in audio_generation.models else None
            keyword = ""
            if maybe_model is not None:
                keyword = " ".join(pieces[2:]).strip()
            else:
                keyword = " ".join(pieces[1:]).strip() if len(pieces) > 1 else ""
            resolved_for_voices = audio_generation.resolve_model(maybe_model)
            if resolved_for_voices is None:
                await tts_cmd.finish("语音生成默认模型未配置")
            await tts_cmd.send("正在获取可用音色，请稍候…")
            try:
                voice_groups = await list_available_voices(resolved_for_voices.provider)
            except GenerationProviderError as exc:
                await tts_cmd.finish(f"音色列表获取失败：{exc}")
            await tts_cmd.finish(_format_voice_groups(voice_groups, keyword=keyword))

        if not rate_limiter.allow("audio_gen", event.user_id, group_id=group_id):
            await tts_cmd.finish("语音生成过于频繁，请稍后再试")
        model_id, voice_id, prompt = _parse_tts_args(raw_args, set(audio_generation.models))
        resolved_model = audio_generation.resolve_model(model_id)
        if resolved_model is None:
            await tts_cmd.finish("语音生成默认模型未配置")

        reply = getattr(event, "reply", None)
        reply_text = ""
        if reply and reply.message:
            reply_text, _ = await _resolve_message_content(bot, reply.message)
        full_prompt = "\n".join(filter(None, [reply_text, prompt])).strip()

        if not full_prompt:
            model_ids = list(audio_generation.models)
            hint = "用法：/tts [模型] [--voice 音色ID] <文本>"
            if len(model_ids) > 1:
                await tts_cmd.finish(
                    f"{hint}\n可用模型：{'、'.join(model_ids)}（默认：{audio_generation.default_model}）"
                )
            await tts_cmd.finish(hint)
        if any(word in full_prompt.lower() for word in audio_generation.prompt_blocklist):
            await tts_cmd.finish("文本包含不允许的内容，请修改后重试")

        await tts_cmd.send("正在生成语音，请稍候…")
        try:
            result = await generate_audio(
                resolved_model.model_config,
                resolved_model.provider,
                full_prompt,
                voice_id=voice_id,
            )
        except GenerationProviderError as exc:
            await tts_cmd.finish(f"语音生成失败：{exc}")
        except Exception as exc:
            await tts_cmd.finish(f"语音生成异常：{type(exc).__name__}: {exc}")

        audio_file = BytesIO(result.audio_bytes)
        await tts_cmd.finish(
            Message([MessageSegment.record(audio_file)])
        )

    music_cmd = on_command("music", priority=10, block=True)

    @music_cmd.handle()
    async def _(bot, event):
        group_id = getattr(event, "group_id", None)
        generation_config = generation_service.get_config()
        if generation_config.load_error:
            await music_cmd.finish(f"音乐生成配置错误：{generation_config.load_error}")
        music_generation = generation_config.music
        if not music_generation.enabled:
            await music_cmd.finish("音乐生成功能未启用")
        if not music_generation.models:
            await music_cmd.finish("音乐生成模型未配置")

        text = str(event.get_message()).strip()
        raw_args = _strip_command_name(text, "music").strip()
        parsed = _parse_music_args(raw_args, set(music_generation.models))

        if parsed.action == "models":
            await music_cmd.finish(_format_music_models(music_generation))

        reply = getattr(event, "reply", None)
        reply_text = ""
        if reply and reply.message:
            reply_text, _ = await _resolve_message_content(bot, reply.message)

        blocklist_text = "\n".join(
            filter(None, [parsed.prompt, parsed.lyrics, parsed.title, reply_text])
        ).lower()
        if any(word in blocklist_text for word in music_generation.prompt_blocklist):
            await music_cmd.finish("文本包含不允许的内容，请修改后重试")

        default_music_model = music_generation.resolve_model(parsed.model_id)
        if default_music_model is None:
            await music_cmd.finish("音乐生成默认模型未配置")

        if parsed.action in {"lyrics", "lyrics_edit"}:
            if not parsed.prompt:
                if parsed.action == "lyrics_edit":
                    await music_cmd.finish(
                        "用法：/music lyrics edit [--title 标题] [--lyrics 现有歌词] <修改要求>\n"
                        "也可以回复一条歌词文本后发送该命令。"
                    )
                await music_cmd.finish("用法：/music lyrics [--title 标题] <主题或要求>")
            source_lyrics = parsed.lyrics or reply_text
            if parsed.action == "lyrics_edit" and not source_lyrics:
                await music_cmd.finish(
                    "歌词编辑模式需要现有歌词。可用 --lyrics 传入，或回复一条歌词文本后再发送命令。"
                )

            await music_cmd.send("正在生成歌词，请稍候…")
            try:
                lyric_result = await generate_lyrics(
                    default_music_model.provider,
                    parsed.prompt,
                    mode="edit" if parsed.action == "lyrics_edit" else "write_full_song",
                    lyrics=source_lyrics,
                    title=parsed.title,
                )
            except GenerationProviderError as exc:
                await music_cmd.finish(f"歌词生成失败：{exc}")
            except Exception as exc:
                await music_cmd.finish(f"歌词生成异常：{type(exc).__name__}: {exc}")

            heading = "歌词已生成" if parsed.action == "lyrics" else "歌词已编辑"
            await _send_lyrics_forward(bot, event, lyric_result, heading)
            await music_cmd.finish()

        if not rate_limiter.allow("music_gen", event.user_id, group_id=group_id):
            await music_cmd.finish("音乐生成过于频繁，请稍后再试")
        if not parsed.prompt:
            model_ids = list(music_generation.models)
            hint = (
                "用法：/music models | /music lyrics [--title 标题] <主题或要求> | "
                "/music lyrics edit [--title 标题] [--lyrics 现有歌词] <修改要求> | "
                "/music [模型] [--instrumental] [--title 标题] [--lyrics 歌词] <风格描述>"
            )
            reply_hint = "也可以回复一条歌词文本后直接发送 /music [模型] <风格描述>。"
            if len(model_ids) > 1:
                await music_cmd.finish(
                    f"{hint}\n可用模型：{'、'.join(model_ids)}（默认：{music_generation.default_model}）\n{reply_hint}"
                )
            await music_cmd.finish(f"{hint}\n{reply_hint}")

        source_lyrics = parsed.lyrics or reply_text
        if parsed.instrumental and source_lyrics:
            await music_cmd.finish("纯音乐模式不需要歌词，请去掉 --lyrics 或不要回复歌词文本。")

        await music_cmd.send("正在生成音乐，请稍候…")
        lyric_result = None
        prompt_for_music = parsed.prompt
        if not parsed.instrumental and not source_lyrics:
            try:
                lyric_result = await generate_lyrics(
                    default_music_model.provider,
                    parsed.prompt,
                    mode="write_full_song",
                    title=parsed.title,
                )
            except GenerationProviderError as exc:
                await music_cmd.finish(f"歌词生成失败：{exc}")
            except Exception as exc:
                await music_cmd.finish(f"歌词生成异常：{type(exc).__name__}: {exc}")
            source_lyrics = lyric_result.lyrics
            prompt_for_music = lyric_result.style_tags or parsed.prompt

        try:
            music_result = await generate_music(
                default_music_model.model_config,
                default_music_model.provider,
                prompt_for_music,
                lyrics=source_lyrics,
                instrumental=parsed.instrumental,
            )
        except GenerationProviderError as exc:
            await music_cmd.finish(f"音乐生成失败：{exc}")
        except Exception as exc:
            await music_cmd.finish(f"音乐生成异常：{type(exc).__name__}: {exc}")

        if lyric_result is not None:
            await _send_lyrics_forward(bot, event, lyric_result, "已自动生成歌词并开始谱曲")
        else:
            lines = [f"音乐已生成（模型：{default_music_model.id}）"]
            if parsed.instrumental:
                lines.append("模式：纯音乐")
            elif parsed.title:
                lines.append(f"标题：{parsed.title}")
            await music_cmd.send("\n".join(lines))

        await music_cmd.finish(Message([MessageSegment.record(BytesIO(music_result.audio_bytes))]))
