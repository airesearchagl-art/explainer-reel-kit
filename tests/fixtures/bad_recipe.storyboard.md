---
id: bad-recipe
title: レシピ名が誤っている台本
schema_version: 1.0.0
audience: A
kind: tool_intro
aspect: "16:9"
output_name: bad_recipe
---

## intro
```yaml
summary: 不正な台本の例
```
不正な台本です。

## s01: 画面を開く
```yaml
image:
  source: manual
  ref: placeholder.png
  label: 説明用再構成図
recipe: zoom_in
```
存在しないレシピ名を使っています。

## outro
```yaml
summary: おわり
```
以上です。
