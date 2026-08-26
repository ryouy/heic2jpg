# Google Photos HEIC Toolkit

Google Photos / Google Takeout から写真をまとめて取り出したときに、iPhone由来の HEIC、JPEG、動画、Google Photos の sidecar JSON が混在して扱いづらくなる問題を整理するための macOS 向けツールです。

## 背景

iPhone の写真を Google Photos にアップロードしても、HEIC が必ず JPEG に変換されるわけではありません。また Google Photos / Google Takeout から一括ダウンロードすると、次のように画像本体とメタデータ JSON が分離して出てくることがあります。

```text
Photos from 2024/
├── IMG_3643.HEIC
├── IMG_3643.HEIC.supplemental-metadata.json
├── IMG_3650.jpg
├── IMG_3650.jpg.supplemental-metadata.json
├── IMG_4000.MOV
└── ...
```

このリポジトリでは、これらを次のような1つのフォルダへ整理します。

```text
all_media/
├── IMG_3643.jpg
├── IMG_3650.jpg
├── IMG_4000.MOV
└── ...
```

## 主な機能

- HEIC / HEIF を JPEG に変換
- 元から JPEG がある場合は JPEG を優先し、HEICとの二重出力を避ける
- Google Photos の sidecar JSON から GPS・説明・不足している撮影時刻を補完
- 元画像に撮影日時がある場合は、JSONのUTC時刻で上書きしない
- 元画像に時刻がなく、JSONに GPS がある場合は、GPSから現地タイムゾーンを推定して撮影時刻を補完
- JPG / PNG / MOV / MP4 などを `all_media` に集約
- 完全に同じファイルは SHA-256 で重複判定
- 同じファイル名で中身が異なる場合は、撮影時刻などを付けて両方保存
- JPEGを撮影日時ベースのファイル名へ一括変更

## 動作環境

macOS を前提にしています。

HEIC → JPEG 変換には macOS 標準の `sips` を使います。

### 依存関係

```bash
brew install exiftool
python3 -m pip install -r requirements.txt
```

## 1. 写真・動画を `all_media` に集約

Google Photos / Takeout のフォルダ群が並んでいる親ディレクトリで実行します。

```bash
python3 collect_media.py . --clean
```

既存の `all_media` があれば削除して最初から作り直します。

元HEICも変換成功後に削除したい場合:

```bash
python3 collect_media.py . --clean --delete-heic
```

安全のため、`--delete-heic` を付けない限り元HEICは残します。

### 撮影時刻の優先順位

撮影日時は次の順序で扱います。

1. 元JPGに入っている撮影日時
2. HEIC自身に入っている撮影日時
3. Google Photos JSON の `photoTakenTime.timestamp` を GPS のタイムゾーンへ変換した日時
4. GPSがなく現地時刻を安全に判定できない場合は、JSON時刻で勝手に上書きしない

Google Photos JSON の Unix timestamp は UTC です。そのまま `DateTimeOriginal` に書くと、日本では9時間、欧州では1〜2時間などのズレが出るため、GPSがある場合のみ現地時間へ変換します。

## 2. JPEGを撮影日時でリネーム

例えば以下のようなファイルを、メタデータの作成日時からリネームできます。

```text
IMG_8486.jpg
DSC_1234.jpg
```

実行:

```bash
python3 rename_by_created.py all_media
```

結果例:

```text
20241030_144034.jpg
20241030_144034_2.jpg
20241103_092117.jpg
```

同じ秒に複数枚撮影されている場合は `_2`, `_3` のように連番を付けます。

日時の優先順位:

1. `ContentCreateDate`
2. `DateTimeOriginal`
3. `CreateDate`

実際に変更せず確認だけしたい場合:

```bash
python3 rename_by_created.py all_media --dry-run
```

サブフォルダも再帰的に対象にする場合:

```bash
python3 rename_by_created.py . --recursive
```

## 3. 過去の処理でできた `__2` ファイルを確認・削除

以前の整理処理などで `IMG_1234__2.jpg` のようなファイルが大量にできた場合の補助ツールです。

まず確認:

```bash
python3 cleanup_suffix2.py all_media
```

実際に削除:

```bash
python3 cleanup_suffix2.py all_media --delete
```

注意: `__2` が本当に不要な重複かどうかは、このスクリプトでは判定しません。削除前に必ず確認してください。

## 推奨ワークフロー

```bash
# 1. 必要ツールを入れる
brew install exiftool
python3 -m pip install -r requirements.txt

# 2. HEIC/JPEG/動画を集約
python3 collect_media.py . --clean --delete-heic

# 3. 結果を確認
open all_media

# 4. 問題なければ撮影日時でファイル名を統一
python3 rename_by_created.py all_media --dry-run
python3 rename_by_created.py all_media
```

## メタデータ確認

1枚のJPEGを確認:

```bash
exiftool all_media/IMG_3643.jpg
```

撮影日時とGPSだけ確認:

```bash
exiftool \
  -ContentCreateDate \
  -DateTimeOriginal \
  -CreateDate \
  -OffsetTimeOriginal \
  -GPSLatitude \
  -GPSLongitude \
  all_media/IMG_3643.jpg
```

## 注意事項

- 重要な写真では、必ず元データのバックアップを取ってから実行してください。
- `--clean` は既存の `all_media` を削除します。
- `--delete-heic` は変換成功後に元HEICを削除します。
- Google Photos / Takeout の出力形式は将来変更される可能性があります。
- HEIC変換は macOS の `sips` に依存しています。
- JSONにGPSが無く、元画像にも撮影時刻が無い場合は、UTC timestampを無理にローカル時刻へ変換しません。

## License

MIT
