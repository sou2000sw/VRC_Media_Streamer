# -*- coding: utf-8 -*-
"""pytest 共通設定。

**テストが利用者の実ファイル（config.json / ログ）を書き換えないようにする。**

`streamer_core.CONFIG_FILE` はモジュール定数の絶対パスなので、素directoryのままテストを
走らせると `StreamerCore` が実ファイルへ保存してしまう。実際に
`standby_image_path` へ pytest の一時ディレクトリのパスが焼き付いた状態で見つかった。

個々のテストに `config_path=` を書き足す方法もあるが、それだと**新しく書かれた
テストが同じ穴を再び開ける**。ここで autouse フィクスチャとして塞いでおく。
"""

import json
import sys

import pytest

import streamer_core


@pytest.fixture(autouse=True)
def isolated_config_file(tmp_path, monkeypatch):
    """各テストの config.json をテスト専用の一時ファイルへ差し替える。"""
    real_path = streamer_core.CONFIG_FILE
    temp_path = str(tmp_path / "config.json")

    # 既定値で種を蒔いておく。「config.json は存在する」前提で書かれたテストがあるため。
    # 利用者の実設定をコピーしないのは、テスト結果が手元の設定に左右されないようにするため。
    seed = dict(streamer_core.DEFAULT_CONFIG)
    # 映像エンコーダーは libx264 に固定する（既定は "auto"）。
    # "auto" のままだと、開発機にNVIDIA GPUがあるかどうかで生成されるFFmpegコマンドが
    # 変わり、同じテストが「GPU付きPCでだけ落ちる」。実際にそうなった:
    # 再エンコード経路の判定を `"libx264" in cmd` で書いていた既存テスト3件が、
    # auto が NVENC を選んだ環境で落ちた。エンコーダー自体の検証は
    # test_hw_encoding.py が担当し、そちらは probe をモックして機種非依存にしてある。
    seed["video_encoder"] = "libx264"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(seed, f, indent=2, ensure_ascii=False)

    monkeypatch.setattr(streamer_core, "CONFIG_FILE", temp_path, raising=False)

    # `from streamer_core import CONFIG_FILE` 相当で自前の束縛を持っているテストモジュールも
    # 追随させる。放っておくと「コアは一時ファイルへ書くのに、テストは実ファイルを読む」
    # という食い違いになる。
    for name, module in list(sys.modules.items()):
        if not name.startswith("test_") or module is None:
            continue
        if getattr(module, "CONFIG_FILE", None) == real_path:
            monkeypatch.setattr(module, "CONFIG_FILE", temp_path, raising=False)

    yield temp_path


@pytest.fixture(autouse=True)
def isolated_log_file(tmp_path, monkeypatch):
    """各テストのログ出力先をテスト専用の一時ファイルへ差し替える。

    `streamer_core.LOG_FILE_PATH` も CONFIG_FILE と同じくモジュール定数の絶対パスで、
    素のまま走らせるとテストの出力が配布物と同じ場所の実ログへ延々と追記される。
    実際に pytest 1回で 289行が実ログへ流れ込み、利用者の操作履歴が埋もれた。
    """
    monkeypatch.setattr(
        streamer_core, "LOG_FILE_PATH", str(tmp_path / "test.log"), raising=False
    )
    yield
