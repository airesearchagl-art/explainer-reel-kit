"""Web 画面の撮影（``erkit capture``）・操作の記録（``erkit record``）・注釈位置の確認画像。"""
from .capture import (  # noqa: F401
    ACTIONS_SCHEMA,
    RESULT_NAME,
    CaptureError,
    crosscheck,
    default_actions_path,
    default_out_dir,
    load_actions,
    load_storyboard,
    map_url,
    plan,
    run_capture,
    validate_actions,
    web_scenes,
)
