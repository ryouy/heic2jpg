# heic2jpg

Google Photos / Google Takeout から落とした **HEIC + sidecar JSON + JPG + 動画** を、macOSでまとめて整理するためのスクリプト集です。

iPhone写真をGoogle Photosへ上げてもHEICのまま残ることがあり、Takeoutでは写真本体とメタデータJSONが分離します。このツールはHEICをJPG化し、撮影日時・GPSなどをできるだけ維持して `all_media` に集約します。

## Setup

```bash
brew install exiftool
python3 -m pip install -r requirements.txt
```

macOS標準の `sips` を使うため、基本的にmacOS向けです。

## 1. HEIC / JPG / 動画を1フォルダにまとめる

```bash
python3 collect_media.py . --clean
```

変換成功後に元HEICも消す場合:

```bash
python3 collect_media.py . --clean --delete-heic
```

出力先は `all_media/` です。

- 同名のHEICとJPGがあればJPGを優先
- HEICしかなければJPGへ変換
- JPG / PNG / MOV / MP4などもまとめてコピー
- sidecar JSONからGPSや不足メタデータを補完
- 元画像に撮影時刻があればJSONのUTC時刻で上書きしない
- 元画像に時刻がなく、JSONにGPSがある場合のみ現地時刻へ変換して補完

## 2. JPGを撮影日時でリネーム

```bash
python3 rename_by_created.py all_media
```

例:

```text
IMG_8486.jpg       -> 20241030_144034.jpg
IMG_8487.jpg       -> 20241030_144034_2.jpg
```

確認だけ:

```bash
python3 rename_by_created.py all_media --dry-run
```

## 3. JPGを2MB程度まで圧縮

解像度は変えず、2MB以下になる範囲で一番高いJPEG品質を選びます。

```bash
python3 compress_jpgs.py all_media --max-mb 2
```

確認だけ:

```bash
python3 compress_jpgs.py all_media --max-mb 2 --dry-run
```

品質50でも2MB以下にならない画像は変更しません。

## 4. JPGを強制的に2MB以下へ

```bash
python3 force_compress_jpgs.py all_media --max-mb 2
```

まずJPEG品質だけを下げ、それでも収まらない場合は解像度も段階的に縮小します。EXIF / GPSなどのメタデータは元画像から戻します。

**このスクリプトはJPGを上書きするため、バックアップを推奨します。**

## その他

過去の処理でできた `__2` ファイルを確認:

```bash
python3 cleanup_suffix2.py all_media
```

削除:

```bash
python3 cleanup_suffix2.py all_media --delete
```

## Files

```text
collect_media.py          HEIC変換・JSONメタデータ統合・メディア集約
rename_by_created.py      撮影日時でJPGをリネーム
compress_jpgs.py          解像度維持で指定サイズ以下を狙う
force_compress_jpgs.py    必要なら縮小して指定サイズ以下へ強制圧縮
cleanup_suffix2.py        __2 ファイルの確認・削除
```

## License

MIT
