"""从现有便携包生成 qtwebview2/widget.py 的 override（加一个 profile 目录覆盖开关）。

为什么要 override：
  * 登录态、1080P+ 画质偏好这些都存在 WebView2 的 user data 目录里（Cookies/Login Data）。
    默认路径是 %LOCALAPPDATA%\\<应用名>\\WebView2_UserData，其中「应用名」由原版程序
    运行时设置（本机是「懒宝浏览器」）。换个解压位置不会丢，但名字不直观、也不好备份。
  * 加一个 MABAO_WEBVIEW_PROFILE 环境变量：设了就固定用那个目录，方便把登录态
    放到自己想放的地方（例如 D:\\二游辅助-profile），也方便备份/迁移。

用法：
    python make_widget_override.py            # 生成/更新 override
    python make_widget_override.py --check    # 只检查是否与现有 override 一致
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\16408\Desktop\二游自动\03_二游辅助")
DEPLOYED = ROOT / "app" / "_internal" / "qtwebview2" / "widget.py"
OVERRIDE = ROOT / "src" / "legacy_original" / "overrides" / "qtwebview2" / "widget.py"

ORIGINAL_BLOCK = """                user_data = self._user_data_folder
                if not self._user_data_folder:
                    app_name = QCoreApplication.applicationName() or "DefaultQtApp"
                    data_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
                    if not data_path:
                        data_path = os.path.join(dotnet.System_.IO.Path.GetTempPath(), app_name)
                    user_data = os.path.join(data_path, "WebView2_UserData")
"""

PATCHED_BLOCK = """                user_data = self._user_data_folder
                if not self._user_data_folder:
                    # 二游辅助本地补丁：登录态/Cookies/画质偏好都跟着这个目录走。
                    # 设了 MABAO_WEBVIEW_PROFILE 就固定用它，否则沿用原版按应用名推导的路径
                    # （%LOCALAPPDATA%\\<应用名>\\WebView2_UserData，与解压位置无关，不会因为换目录丢登录）。
                    profile_override = os.environ.get("MABAO_WEBVIEW_PROFILE", "").strip()
                    if profile_override:
                        user_data = os.path.join(profile_override, "WebView2_UserData")
                    else:
                        app_name = QCoreApplication.applicationName() or "DefaultQtApp"
                        data_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
                        if not data_path:
                            data_path = os.path.join(dotnet.System_.IO.Path.GetTempPath(), app_name)
                        user_data = os.path.join(data_path, "WebView2_UserData")
"""

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--source", default=str(DEPLOYED))
    args = parser.parse_args(argv)

    source = Path(args.source)
    if not source.is_file():
        print(f"[!] 找不到已部署的 widget.py：{source}")
        return 2
    text = source.read_text(encoding="utf-8")
    if PATCHED_BLOCK in text:
        print("已打过补丁（源文件就是 override），直接复制")
        patched = text
    elif ORIGINAL_BLOCK in text:
        patched = text.replace(ORIGINAL_BLOCK, PATCHED_BLOCK, 1)
        print("已生成带 MABAO_WEBVIEW_PROFILE 支持的版本")
    else:
        print("[!] 没找到预期的 user_data 代码块，请人工检查源文件")
        return 3

    if args.check:
        if OVERRIDE.is_file() and OVERRIDE.read_text(encoding="utf-8") == patched:
            print("override 已是最新")
            return 0
        print("override 需要更新")
        return 1

    OVERRIDE.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDE.write_text(patched, encoding="utf-8")
    print(f"已写入 {OVERRIDE}（{len(patched)} 字符）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
