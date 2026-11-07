---
id: window-condensation
title: 冬の窓の結露のしくみと減らし方
schema_version: kit-1.1.0
audience: A
kind: explainer
confidentiality: general
aspect: "16:9"
output_name: window_condensation
---

# 冬の窓の結露のしくみと減らし方

<!--
解説（kind: explainer）のサンプル。構成の決まり: 問い → しくみ → 条件・比べる → 減らし方 → まとめ（5 シーン）。
数値・事実の根拠は隣の SOURCES.md（[1] 日本サッシ協会、[2] 三菱電機）。確かめたことだけを書いている。
窓ガラスの種類ごとの性能の数値は、確かめた資料に無いので使わない。
-->

## intro
```yaml
summary: 冬の朝、窓に水滴がつくのはなぜか。しくみと、家でできる減らし方を解説します。
prerequisites: []
duration_note: 約 2 分
```
冬の朝、カーテンを開けると、窓ガラスに水滴がびっしり。この水滴は、どこから来るのでしょうか。しくみが分かると、減らし方も見えてきます。

## s01: 身近な場面で考える
```yaml
where: 説明図
image:
  source: generated
  ref: assets/s01_question.png
  label: 説明用再構成図
on_screen_text: 窓の水滴はどこから来る？
recipe: highlight_box
recipe_params:
  mark: [everyday, topic]
capture:
  tool: html
  src: diagrams/s01_question.html
  prompt: 冷たい飲みものの缶（身近なもの）と冬の窓ガラス（本題）を並べたたとえの図
```
夏に冷たい飲みものの缶を出しておくと、まわりに水滴がつきます。缶から水がしみ出したのではありません。

冬の窓ガラスも同じです。冷えたガラスに、部屋の空気に含まれていた水蒸気が、水滴になってつきます。

## s02: 水滴ができる順にたどる
```yaml
where: 説明図
image:
  source: generated
  ref: assets/s02_flow.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: [step_1, step_2, step_3, step_4]
capture:
  tool: html
  src: diagrams/s02_flow.html
  prompt: 暖かい空気から結露までを 4 段の矢印でつないだ流れ
```
空気は、暖かいほど多くの水蒸気を含むことができます。暖房した部屋の空気には、水蒸気がたくさん含まれています。

その空気が、外の寒さで冷えた窓ガラスに触れると、ガラスの近くで冷やされます。

冷やされた空気は、含める水蒸気の量が減ります。水滴ができ始める温度を、露点といいます。たとえば、二十度で湿度六十パーセントの空気なら、露点はおよそ十二度です。

露点より冷たい面では、持ちきれなくなった水蒸気が水滴になります。これが結露です。

## s03: 結露の二つの条件を知る
```yaml
where: 説明図
image:
  source: generated
  ref: assets/s03_conditions.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: [card_1, card_2, card_3]
capture:
  tool: html
  src: diagrams/s03_conditions.html
  prompt: 結露にかかわる 2 つの条件（温度差・湿度）と、窓を変えても起きることを 3 枚のカードで並べた図
```
結露にかかわる条件は、二つです。一つめは、部屋の中と外の温度の差です。

二つめは、部屋の中の湿度です。空気に含まれる水蒸気が多いほど、露点が高くなり、水滴ができやすくなります。

断熱性の高いサッシや、ガラスを二枚重ねた窓でも、この二つの条件しだいで、結露することがあります。

## s04: 暖房の種類を比べる
```yaml
where: 説明図
image:
  source: generated
  ref: assets/s04_heaters.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: [row_open, row_closed]
capture:
  tool: html
  src: diagrams/s04_heaters.html
  prompt: 暖房の種類ごとに、部屋に水蒸気を出すかを比べた表
```
湿度を左右するものの一つが、暖房です。部屋の中で燃やす、開放型の石油やガスのストーブは、水蒸気を出します。

エアコンや電気ストーブ、密閉型の暖房機は、部屋に水蒸気を出しません。結露が気になる部屋では、こちらを選ぶのが一つの方法です。

## s05: 結露を減らす
```yaml
where: 説明図
image:
  source: generated
  ref: assets/s05_reduce.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: [card_1, card_2, card_3]
capture:
  tool: html
  src: diagrams/s05_reduce.html
  prompt: 家でできる結露の減らし方を 3 枚のカードで並べた図
```
一つめは、こまめな換気です。料理やお風呂の間とその後、寝る前にも、湿った空気を外に出します。

二つめは、洗濯物の室内干しを控えることです。干した洗濯物からは、たくさんの水蒸気が出ます。

三つめは、加湿器を使いすぎないことです。お風呂のフタを開けたままにしないことも、水蒸気を減らします。

## outro
```yaml
summary: 結露は、暖かい空気の水蒸気が冷たい窓で冷やされて水滴になる現象です。温度差と湿度で起き、換気と水蒸気を減らす工夫で減らせます。
checks:
  - 冬の朝、どの部屋の窓に結露が多いか
  - 部屋で使っている暖房が、水蒸気を出す種類か
next: 料理・お風呂の後と寝る前の換気から始めてみる
```
結露は、暖かい空気に含まれる水蒸気が、冷たい窓で冷やされて水滴になる現象です。まずは、どの部屋の窓に多いかと、使っている暖房の種類を確かめてみてください。
