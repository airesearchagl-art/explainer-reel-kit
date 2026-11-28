"""コード描画（render_mode: interactive）。

ナレーションの時刻に合わせて、Python の場面コードか scenes.yaml（部品の指定）で 1 フレームずつ描き、ffmpeg で MP4 にする。
PowerPoint を使わない。描画はこの PC の中だけで行い、ネットワークを使わない。使い方は README.md。

``erkit make`` から呼ぶ入口は :mod:`.pipeline`（:func:`~.pipeline.precheck_scenes`・:func:`~.pipeline.render_storyboard`・
:func:`~.pipeline.verify_storyboard`）。
"""
RENDER_MODES = ("slides", "interactive")
DEFAULT_RENDER_MODE = "slides"
