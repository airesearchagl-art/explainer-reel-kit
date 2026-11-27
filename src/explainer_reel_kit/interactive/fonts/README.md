# 同梱の書体（interactive）

コード描画（render_mode: interactive）が使う書体。OS の差で絵が変わらないように同梱する。
日本語だけの Noto Sans JP の OTF（Regular・Bold）の 2 つだけ（TTC は入れない）。

| ファイル | 書体 | 版 | 大きさ | sha256 |
|---|---|---|---|---|
| `NotoSansJP-Regular.otf` | Noto Sans JP Regular | Version 2.004 | 4,533,028 | `dff723ba59d57d136764a04b9b2d03205544f7cd785a711442d6d2d085ac5073` |
| `NotoSansJP-Bold.otf` | Noto Sans JP Bold | Version 2.004 | 4,656,448 | `1b0edfb500b73a4fa8a4fcaae1bbbd403994e08e73e3e0da37e70d3853f42c5f` |
| `OFL.txt` | ライセンス文（配布元の `LICENSE` のまま） | — | 4,301 | `6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2` |

- 入手先: [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk) のタグ `Sans2.004`（2022-01-27 のリリース）
  - `https://raw.githubusercontent.com/notofonts/noto-cjk/Sans2.004/Sans/SubsetOTF/JP/NotoSansJP-Regular.otf`
  - `https://raw.githubusercontent.com/notofonts/noto-cjk/Sans2.004/Sans/SubsetOTF/JP/NotoSansJP-Bold.otf`
  - `https://raw.githubusercontent.com/notofonts/noto-cjk/Sans2.004/LICENSE`
- 入手日: 2026-11-26。版は書体の name テーブル（Version 2.004）で確かめた
- 著作権の表記（書体の name テーブルの ID 0・7 のまま）: `© 2014-2021 Adobe (http://www.adobe.com/).`／`Noto is a trademark of Google Inc.`
- ライセンス: SIL Open Font License, Version 1.1（`OFL.txt`。書体の name テーブルの ID 13・14 も同じ OFL 1.1 を指す）。書体だけを売らない限り、ソフトウェアに同梱して配ってよい。書体は改変しない（改変するときは OFL の決まりに従う）
- 使い方: `engine.font('R' | 'B', 大きさ)`（レイアウトは Pillow の BASIC）。差し替えるときは、この表と `engine.FONT_FILES` をそろえる
