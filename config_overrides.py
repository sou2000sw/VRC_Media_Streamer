# -*- coding: utf-8 -*-
"""CLI 引数・環境変数による設定オーバーライドの組み立て（タスク19）。

このモジュールは GUI に依存しない。単体テストから直接 import できるようにするためで、
`customtkinter` 等をここへ持ち込まないこと。

設定の優先順位は CLI > 環境変数 > config.json > DEFAULT_CONFIG。
ここが返すのは上位2層（CLI / 環境変数）だけで、実際の合成は
`streamer_core.LayeredConfig` が行う。ここで作った値は「その起動限りの指定」であり、
config.json には決して書かれない。
"""

import argparse
import os

from streamer_core import DEFAULT_CONFIG

ENV_PREFIX = "VRCMS_"

# プロセス一覧やシェル履歴から第三者に見えてしまう値。--set では受け付けず、
# 環境変数からのみ受け取る。
SECRET_KEYS = frozenset({"topaz_stream_key", "generic_rtmp_key", "web_password"})

_TRUE_WORDS = {"1", "true", "yes", "on"}
_FALSE_WORDS = {"0", "false", "no", "off"}

# --radio / --no-radio のように、1つのフラグが複数のキーへ展開されるもの
_RADIO_ON = {"playback_mode": "radio", "radio_mode": True}
_RADIO_OFF = {"playback_mode": "video", "radio_mode": False}


def coerce_config_value(key, raw):
    """文字列 `raw` を `DEFAULT_CONFIG[key]` の型へ変換する。

    未知のキーは黙って通さない。設定名の打ち間違いが「指定したのに効かない」という
    最も分かりにくい形で表面化するため。
    """
    if key not in DEFAULT_CONFIG:
        raise ValueError(f"Unknown config key: '{key}'")

    if isinstance(raw, bool) or not isinstance(raw, str):
        # 既に型が付いている値（テストやプログラムからの呼び出し）はそのまま通す
        return raw

    expected = DEFAULT_CONFIG[key]
    text = raw.strip()

    # bool は int の派生なので、必ず bool を先に判定する。
    # 逆にすると loop_queue=true が int 変換へ回って壊れる。
    if isinstance(expected, bool):
        lowered = text.lower()
        if lowered in _TRUE_WORDS:
            return True
        if lowered in _FALSE_WORDS:
            return False
        raise ValueError(
            f"Config key '{key}' expects a boolean "
            f"(one of: {', '.join(sorted(_TRUE_WORDS | _FALSE_WORDS))}), got '{raw}'"
        )

    if isinstance(expected, int):
        try:
            return int(text)
        except (TypeError, ValueError):
            raise ValueError(f"Config key '{key}' expects an integer, got '{raw}'")

    if isinstance(expected, str):
        return text

    raise ValueError(f"Config key '{key}' has an unsupported type: {type(expected).__name__}")


def parse_set_assignments(items):
    """`--set KEY=VALUE` の並びを {key: 変換済みの値} にする。"""
    result = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"--set expects KEY=VALUE, got '{item}'")
        raw_key, raw_value = item.split("=", 1)
        key = raw_key.strip().lower()
        if key in SECRET_KEYS:
            raise ValueError(
                f"Config key '{key}' cannot be set with --set because command line "
                f"arguments are visible to other users via the process list. "
                f"Use the environment variable {ENV_PREFIX}{key.upper()} instead."
            )
        result[key] = coerce_config_value(key, raw_value)
    return result


def collect_env_overrides(environ):
    """環境変数 `VRCMS_*` から設定オーバーライドを拾う。

    未知のキーや変換できない値は、そのキーだけ無視する（例外にしない）。
    環境変数は他の用途と偶然衝突しうるため、起動そのものを止めるのは行き過ぎ。
    """
    result = {}
    for name, raw_value in (environ or {}).items():
        if not name.startswith(ENV_PREFIX):
            continue
        key = name[len(ENV_PREFIX):].strip().lower()
        if key not in DEFAULT_CONFIG:
            continue
        try:
            result[key] = coerce_config_value(key, raw_value)
        except ValueError:
            continue
    return result


def _parse_resolution(text):
    """'1920x1080' を (1920, 1080) にする。"""
    lowered = str(text).strip().lower()
    if "x" not in lowered:
        raise argparse.ArgumentTypeError(f"--resolution expects WxH (e.g. 1280x720), got '{text}'")
    raw_w, _, raw_h = lowered.partition("x")
    try:
        width, height = int(raw_w), int(raw_h)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--resolution expects WxH (e.g. 1280x720), got '{text}'")
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError(f"--resolution must be positive, got '{text}'")
    return width, height


def add_config_arguments(parser):
    """設定オーバーライド系の引数を parser に足す。

    --headless / --tunnel / --no-tunnel / --port / --host は呼び出し側で既に
    定義されているため、ここでは追加しない。
    """
    parser.add_argument("--config", type=str, default=None,
                        help="Path to config.json (default: alongside the executable)")
    parser.add_argument("--output-mode", type=str, default=None,
                        choices=["hls", "topaz", "generic_rtmp"],
                        help="Streaming destination for this session only")
    parser.add_argument("--resolution", type=_parse_resolution, default=None,
                        help="RTMP output resolution as WxH (e.g. 1280x720)")
    parser.add_argument("--bitrate", type=int, default=None,
                        help="RTMP video bitrate in kbps")
    parser.add_argument("--fps", type=int, default=None,
                        help="RTMP output frame rate")
    parser.add_argument("--radio", action="store_true",
                        help="Start in BGM/radio playback mode")
    parser.add_argument("--no-radio", action="store_true",
                        help="Start in normal video playback mode")
    parser.add_argument("--video-encoder", type=str, default=None,
                        choices=["auto", "libx264", "h264_nvenc", "h264_qsv", "h264_amf"],
                        help="Video encoder for this session (default: config.json)")
    parser.add_argument("--host-only", action="store_true",
                        help="Disable the web remote (host PC only, task 21)")
    parser.add_argument("--web-remote", action="store_true",
                        help="Enable the web remote (overrides config.json for this session)")
    parser.add_argument("--set", action="append", default=None, metavar="KEY=VALUE",
                        dest="set_values",
                        help="Override any config.json key for this session (repeatable)")
    return parser


def build_overrides(args, environ=None):
    """CLI 引数と環境変数から {key: (value, source)} を組み立てる。

    後に適用したものが勝つ。環境変数 → --set → 個別フラグ の順なので、
    明示的な引数ほど強い。
    """
    overrides = {}

    def apply(mapping, source):
        for key, value in mapping.items():
            overrides[key] = (value, source)

    apply(collect_env_overrides(environ if environ is not None else os.environ), "env")
    apply(parse_set_assignments(getattr(args, "set_values", None)), "cli")

    radio_on = bool(getattr(args, "radio", False))
    radio_off = bool(getattr(args, "no_radio", False))
    if radio_on and radio_off:
        raise ValueError("--radio and --no-radio cannot be used together")
    if radio_on:
        apply(_RADIO_ON, "cli")
    elif radio_off:
        apply(_RADIO_OFF, "cli")

    output_mode = getattr(args, "output_mode", None)
    if output_mode is not None:
        apply({"output_mode": output_mode}, "cli")

    resolution = getattr(args, "resolution", None)
    if resolution is not None:
        width, height = resolution
        apply({"rtmp_video_width": width, "rtmp_video_height": height}, "cli")

    bitrate = getattr(args, "bitrate", None)
    if bitrate is not None:
        apply({"rtmp_video_bitrate_kbps": int(bitrate)}, "cli")

    fps = getattr(args, "fps", None)
    if fps is not None:
        apply({"rtmp_fps": int(fps)}, "cli")

    port = getattr(args, "port", None)
    if port is not None:
        apply({"port": int(port)}, "cli")

    host = getattr(args, "host", None)
    if host is not None:
        apply({"host": host}, "cli")

    # --tunnel / --no-tunnel は store_true が2本なので、指定されたときだけ効かせる
    if bool(getattr(args, "tunnel", False)):
        apply({"enable_tunnel": True}, "cli")
    elif bool(getattr(args, "no_tunnel", False)):
        apply({"enable_tunnel": False}, "cli")

    video_encoder = getattr(args, "video_encoder", None)
    if video_encoder is not None:
        apply({"video_encoder": str(video_encoder)}, "cli")

    # --host-only / --web-remote も同じ形。閉じる側を後に置き、両方指定なら閉じる方を採る
    # （安全側に倒す）。
    if bool(getattr(args, "web_remote", False)):
        apply({"enable_web_remote": True}, "cli")
    if bool(getattr(args, "host_only", False)):
        apply({"enable_web_remote": False}, "cli")

    return overrides


def describe_overrides(overrides):
    """起動ログ用の1行。秘匿キーは値を出さない。"""
    if not overrides:
        return ""
    parts = []
    for key in sorted(overrides):
        value, source = overrides[key]
        shown = "********" if key in SECRET_KEYS else value
        parts.append(f"{key}={shown}({source})")
    return ", ".join(parts)
