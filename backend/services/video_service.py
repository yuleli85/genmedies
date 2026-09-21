"""
视频合并服务 — 使用 FFmpeg 将多个小视频合成为一个完整视频
"""
import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path


async def merge_videos(video_paths: list[Path], output_path: Path) -> str:
    """将多个视频 concat 合并，各分镜已内置淡入淡出，无需 xfade"""
    if not video_paths:
        raise ValueError("没有可合并的视频文件")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for vp in video_paths:
            f.write(f"file '{vp.resolve()}'\n")
        list_file = f.name

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c:v", "libx264", "-crf", "23", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(*cmd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await proc.communicate()
    Path(list_file).unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg 合并失败: {stderr.decode()[-500:]}")
    return str(output_path)


async def _merge_concat(video_paths: list[Path], output_path: Path) -> str:
    return await merge_videos(video_paths, output_path)


async def mix_audio_into_video(video_path: Path, audio_path: Path, output_path: Path) -> str:
    """将 TTS 音频混入视频，保留原始音轨并混合，视频循环补足音频时长"""
    FADE = 0.3

    probe = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await probe.communicate()
    try:
        audio_dur = float(stdout.decode().strip())
    except ValueError:
        audio_dur = 0.0

    # 检测视频是否有音频流
    probe2 = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet",
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        str(video_path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout2, _ = await probe2.communicate()
    has_audio = bool(stdout2.decode().strip())

    fade_out_st = max(audio_dur - FADE, 0)

    if has_audio:
        # 混合原始音频（降低音量）和 TTS 音频
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", str(video_path),
            "-i", str(audio_path),
            "-filter_complex",
            f"[0:a]volume=0.3[orig];"
            f"[1:a]afade=t=in:st=0:d={FADE},afade=t=out:st={fade_out_st:.2f}:d={FADE}[tts];"
            f"[orig][tts]amix=inputs=2:duration=longest:dropout_transition=2[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-t", f"{audio_dur:.3f}",
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ]
    else:
        # 视频无音轨，只用 TTS
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", str(video_path),
            "-i", str(audio_path),
            "-filter_complex",
            f"[1:a]afade=t=in:st=0:d={FADE},afade=t=out:st={fade_out_st:.2f}:d={FADE}[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-t", f"{audio_dur:.3f}",
            "-c:v", "libx264", "-crf", "23", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ]

    proc = await asyncio.create_subprocess_exec(*cmd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg 混音失败: {stderr.decode()[-400:]}")
    return str(output_path)


async def image_to_video_ffmpeg(
    image_path: Path,
    output_path: Path,
    duration: int = 5,
    portrait_path: Path | None = None,
) -> str:
    """图片转视频：Ken Burns 缩放 + 淡入淡出 + 可选画中画人物"""
    fps = 25
    frames = duration * fps
    FADE = 0.4  # 淡入淡出时长

    # Ken Burns 缩放
    zoom = (
        f"scale=8000:-1,"
        f"zoompan=z='min(zoom+0.0008,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s=1920x1080:fps={fps}"
    )
    # 淡入淡出（视频+音频）
    fade = f"fade=t=in:st=0:d={FADE},fade=t=out:st={duration - FADE:.2f}:d={FADE}"

    if portrait_path and portrait_path.exists():
        pip = (
            f"[1:v]scale=-1:280,format=yuva420p[pip];"
            f"[base][pip]overlay=W-w-30:H-h-30[vout]"
        )
        vfilter = f"[0:v]{zoom}[base];{pip};[vout]{fade}[final]"
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(image_path),
            "-loop", "1", "-i", str(portrait_path),
            "-filter_complex", vfilter,
            "-map", "[final]",
            "-t", str(duration),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
            # 添加静音音轨方便 concat 重编码时有 aac 流
            "-af", f"aevalsrc=0:d={duration},apad,afade=t=in:st=0:d={FADE},afade=t=out:st={duration - FADE:.2f}:d={FADE}",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(image_path),
            "-vf", f"{zoom},{fade}",
            "-t", str(duration),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
            "-af", f"aevalsrc=0:d={duration},apad,afade=t=in:st=0:d={FADE},afade=t=out:st={duration - FADE:.2f}:d={FADE}",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ]

    proc = await asyncio.create_subprocess_exec(*cmd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg 图转视频失败: {stderr.decode()[-400:]}")
    return str(output_path)


async def slide_to_video_static(
    image_path: Path,
    output_path: Path,
    duration: int = 8,
) -> str:
    """PPT 幻灯片转视频：静态展示，无缩放无淡入淡出，避免文字闪烁"""
    fps = 25
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image_path),
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=white",
        "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-preset", "fast", "-crf", "20",
        "-af", f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=0:{duration}",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(*cmd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg 幻灯片转视频失败: {stderr.decode()[-400:]}")
    return str(output_path)


async def merge_with_transitions(video_paths: list[Path], output_path: Path, transition_dur: float = 0.5) -> str:
    """合并视频，相邻镜头间添加交叉淡入淡出转场"""
    if not video_paths:
        raise ValueError("没有可合并的视频文件")
    if len(video_paths) == 1:
        import shutil
        shutil.copy2(video_paths[0], output_path)
        return str(output_path)

    # ── 预处理：确保所有视频都有音频流（无声的补静音轨）──
    preprocessed = []
    tmpdir = tempfile.mkdtemp(prefix="s2v_merge_")
    for i, vp in enumerate(video_paths):
        probe_a = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-select_streams", "a",
            "-show_entries", "stream=index", "-of", "csv=p=0",
            str(vp),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout_a, _ = await probe_a.communicate()
        if stdout_a.decode().strip():
            preprocessed.append(vp)
        else:
            # 补静音轨
            fixed = Path(tmpdir) / f"audio_fixed_{i:03d}{vp.suffix}"
            await add_silent_audio(vp, fixed)
            preprocessed.append(fixed)

    try:
        return await _xfade_merge(preprocessed, output_path, transition_dur)
    except Exception as e:
        logging.warning(f"[video] xfade merge failed ({e}), fallback to concat")
        return await merge_videos(preprocessed, output_path)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


async def _xfade_merge(video_paths: list[Path], output_path: Path, transition_dur: float = 0.5) -> str:
    """内部：用 xfade 合并视频（所有输入必须有音频流）"""
    # 获取每个视频时长
    durations = []
    for vp in video_paths:
        probe = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(vp),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await probe.communicate()
        try:
            durations.append(float(stdout.decode().strip()))
        except ValueError:
            durations.append(5.0)

    n = len(video_paths)
    input_args = []
    for vp in video_paths:
        input_args.extend(["-i", str(vp)])

    # 逐层 xfade 视频
    video_filters = []
    current_label = "[0:v]"
    for i in range(n - 1):
        next_label = f"[{i+1}:v]"
        out_label = f"[v{i}]"
        if i == 0:
            offset = durations[0] - transition_dur
        else:
            accumulated = sum(durations[:i+1]) - i * transition_dur
            offset = accumulated - transition_dur
        video_filters.append(
            f"{current_label}{next_label}xfade=transition=fade:duration={transition_dur}:offset={offset:.3f}{out_label}"
        )
        current_label = out_label

    # 音频 concat
    audio_filter = "".join(f"[{i}:a]" for i in range(n))
    audio_filter += f"concat=n={n}:v=0:a=1[aout]"

    filter_complex = ";".join(video_filters) + ";" + audio_filter

    cmd = [
        "ffmpeg", "-y",
        *input_args,
        "-filter_complex", filter_complex,
        "-map", f"[v{n-2}]",
        "-map", "[aout]",
        "-c:v", "libx264", "-crf", "20", "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(*cmd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode()[-600:]
        raise RuntimeError(f"xfade merge failed: {err[:300]}")
    return str(output_path)


async def add_silent_audio(video_path: Path, output_path: Path) -> str:
    """为没有音轨的视频添加静音音轨"""
    probe = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await probe.communicate()
    try:
        duration = float(stdout.decode().strip())
    except ValueError:
        duration = 5.0

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100:d={duration}",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(*cmd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg 添加静音失败: {stderr.decode()[-400:]}")
    return str(output_path)
