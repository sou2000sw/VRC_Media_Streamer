# -*- coding: utf-8 -*-
"""アプリのバージョン。**ここが唯一の出所**。

以前は build_exe.py の APP_VERSION と ui/index.html のバッジが別々に書かれており、
UI 側の更新が漏れて v2.8.0 / v2.9.0 の2リリースにわたり「v2.7.0」と表示されていた。
表示は /api/status の app_version 経由で配るので、ここを直せば全部が追随する。

依存を持たせないこと（build_exe.py からも import するため）。
"""

APP_VERSION = "2.10.3"
