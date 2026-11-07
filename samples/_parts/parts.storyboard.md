---
id: explainer-parts
title: 解説の説明図の部品（見本）
schema_version: kit-1.1.0
audience: A
kind: explainer
confidentiality: general
aspect: "16:9"
output_name: explainer_parts
---

# 解説の説明図の部品（見本）

<!--
説明図の部品 7 種の見本を、erkit diagram で描くための台本（samples/_parts/README.md）。
動画にするためのものではない。図の中の値は見本（説明のための例）で、出典のある値ではない。
-->

## intro
```yaml
summary: 解説の説明図で使う 7 つの部品の見本です。
duration_note: 未計測
```
解説の説明図で使う部品の見本です。

## s01: 層の重なりを見る
```yaml
where: 説明図
image:
  source: generated
  ref: assets/section.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: layer_air
capture:
  tool: html
  src: section.html
  prompt: 部品「断面図（層の重なり）」の見本
```
部品「断面図」の見本です。

## s02: 3 つを比べる
```yaml
where: 説明図
image:
  source: generated
  ref: assets/compare.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: row_coated
capture:
  tool: html
  src: compare.html
  prompt: 部品「比較表」の見本
```
部品「比較表」の見本です。

## s03: 目安の範囲を知る
```yaml
where: 説明図
image:
  source: generated
  ref: assets/range.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: band_coated
capture:
  tool: html
  src: range.html
  prompt: 部品「数値の範囲（帯と目安）」の見本
```
部品「数値の範囲」の見本です。

## s04: 起きる順にたどる
```yaml
where: 説明図
image:
  source: generated
  ref: assets/flow.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: step_2
capture:
  tool: html
  src: flow.html
  prompt: 部品「フロー（矢印の流れ）」の見本
```
部品「フロー」の見本です。

## s05: 方法を並べる
```yaml
where: 説明図
image:
  source: generated
  ref: assets/cards.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: card_2
capture:
  tool: html
  src: cards.html
  prompt: 部品「カード（2〜4 枚）」の見本
```
部品「カード」の見本です。

## s06: 条件で選ぶ
```yaml
where: 説明図
image:
  source: generated
  ref: assets/branch.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: question
capture:
  tool: html
  src: branch.html
  prompt: 部品「条件の分岐」の見本
```
部品「条件の分岐」の見本です。

## s07: 身近なものにたとえる
```yaml
where: 説明図
image:
  source: generated
  ref: assets/analogy.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: everyday
capture:
  tool: html
  src: analogy.html
  prompt: 部品「たとえ（身近なもの）」の見本
```
部品「たとえ」の見本です。

## outro
```yaml
summary: 部品を組み合わせて、解説の説明図を作ります。
```
以上が部品の見本です。
