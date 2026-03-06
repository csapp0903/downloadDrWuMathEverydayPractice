"""
B站合集视频截图工具 (优化版 v2)

功能：
1. 通过 B站 API 直接获取合集视频列表（无需浏览器，速度快且稳定）
2. 正则匹配找到目标视频
3. 首次运行弹出浏览器让用户登录B站，登录态永久保存在独立 profile 中
4. 后续运行使用 headless 静默模式，在后台完成截图

依赖：pip install selenium requests

首次使用：
  运行脚本 → 浏览器弹出B站登录页 → 手动登录 → 关闭登录页 → 自动截图
后续使用：
  运行脚本 → 全程后台静默完成，无浏览器窗口弹出
"""

import re
import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options as ChromeOptions


# ======================== 配置区 ========================

# B站用户 mid 和合集 season_id（从合集URL中提取）
# 合集URL: https://space.bilibili.com/688379639/lists/6735208?type=season
MID = "688379639"
SEASON_ID = "6735208"

# 视频标题匹配规则
TITLE_PATTERN = re.compile(r"27考研.*题")

# ChromeDriver 路径
CHROME_DRIVER_PATH = r"C:\Users\LiGuangxiao\Desktop\chromedriver.exe"

# Selenium 专用的用户数据目录（独立于日常 Chrome，不会冲突）
SELENIUM_PROFILE_DIR = r"C:\Users\LiGuangxiao\AppData\Local\Google\Chrome\SeleniumProfile"

# 登录完成的标记文件（存在即表示已经登录过，可以使用 headless 模式）
LOGIN_DONE_FLAG = os.path.join(SELENIUM_PROFILE_DIR, ".bilibili_logged_in")

# 截图保存目录
SCREENSHOT_DIR = "bilibili_screenshots"

# 视频加载后等待秒数（等视频画面出现题目）
VIDEO_WAIT_SECONDS = 2 # 3

# ★★★ 是否强制显示浏览器窗口（设为 True 则每次都弹出窗口，方便调试）★★★
FORCE_SHOW_BROWSER = False


# ======================== 步骤1：通过API获取视频列表 ========================

def fetch_video_list(mid: str, season_id: str) -> list[dict]:
    """
    调用B站 Web API 获取合集中的所有视频。
    返回按时间正序排列的视频列表（最早发布的在前面）。
    """
    api_url = "https://api.bilibili.com/x/polymer/web-space/seasons_archives_list"
    all_videos = []
    page = 1
    page_size = 30

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://space.bilibili.com/{mid}",
    }

    print(f"正在通过API获取合集 (mid={mid}, season_id={season_id}) 的视频列表...")

    while True:
        params = {
            "mid": mid,
            "season_id": season_id,
            "sort_reverse": "false",
            "page_num": str(page),
            "page_size": str(page_size),
        }
        try:
            resp = requests.get(api_url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"API 请求失败: {e}")
            return []

        if data.get("code") != 0:
            print(f"API 返回错误: code={data.get('code')}, message={data.get('message')}")
            return []

        archives = data.get("data", {}).get("archives", [])
        if not archives:
            break

        all_videos.extend(archives)
        total = data.get("data", {}).get("page", {}).get("total", 0)
        print(f"  第 {page} 页: 获取到 {len(archives)} 个视频 (累计 {len(all_videos)}/{total})")

        if len(all_videos) >= total:
            break
        page += 1

    print(f"共获取到 {len(all_videos)} 个视频。\n")
    return all_videos


# ======================== 步骤2：匹配目标视频 ========================

def find_target_video(videos: list[dict], pattern: re.Pattern) -> dict | None:
    """
    从视频列表中找到最后一个（最新的）匹配正则的视频。
    """
    print("开始正则匹配目标视频...")
    for video in reversed(videos):
        title = video.get("title", "")
        if pattern.search(title):
            bvid = video.get("bvid", "")
            url = f"https://www.bilibili.com/video/{bvid}"
            print(f"  ✅ 匹配成功: 《{title}》")
            print(f"     BV号: {bvid}")
            print(f"     链接: {url}\n")
            return {"title": title, "bvid": bvid, "url": url}

    print("  ❌ 未找到匹配的视频。\n")
    return None


# ======================== 步骤3：构建 Chrome 选项 ========================

def build_chrome_options(headless: bool = False) -> ChromeOptions:
    """
    构建 Chrome 启动选项。
    headless=True 时浏览器在后台静默运行，不弹出窗口。
    """
    options = ChromeOptions()
    options.add_argument("--mute-audio")
    options.add_argument("--remote-allow-origins=*")
    options.add_argument(f"--user-data-dir={SELENIUM_PROFILE_DIR}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--disable-extensions")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")

    # ★★★ 【修改位置 - Headless 模式开关】★★★
    # 下面这段控制浏览器是否在后台静默运行
    # --headless=new 是 Chrome 109+ 的新版 headless，渲染能力接近正常浏览器
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        # headless 模式下设置合理的窗口大小，确保截图完整
        options.add_argument("--window-size=1920,1080")

    return options


# ======================== 步骤4：首次登录 ========================

def first_time_login():
    """
    首次运行时弹出浏览器，打开B站登录页面，等待用户手动登录。
    登录完成后在 profile 目录下写入标记文件，后续运行将跳过此步骤。
    """
    print("=" * 60)
    print("【首次运行】需要登录B站账号以获取高清画质")
    print("  浏览器即将打开B站登录页面，请手动完成登录。")
    print("  登录成功后，回到此窗口按 Enter 键继续。")
    print("=" * 60)

    os.makedirs(SELENIUM_PROFILE_DIR, exist_ok=True)

    # 首次登录必须显示浏览器窗口（不能 headless）
    options = build_chrome_options(headless=False)
    service = Service(executable_path=CHROME_DRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)

    try:
        # 打开B站登录页
        driver.get("https://passport.bilibili.com/login")
        print("\n⏳ 等待您在浏览器中登录...")
        print("   登录完成后，请回到这个命令行窗口按 Enter 键。\n")

        input(">>> 按 Enter 键确认已登录完成...")

        # 访问一下首页，让 Cookie 完整保存
        driver.get("https://www.bilibili.com")
        time.sleep(2)

        # 写入标记文件
        with open(LOGIN_DONE_FLAG, "w", encoding="utf-8") as f:
            f.write(f"logged_in_at={time.strftime('%Y-%m-%d %H:%M:%S')}\n")

        print("✅ 登录状态已保存！后续运行将自动使用此账号，浏览器在后台静默运行。\n")

    except Exception as e:
        print(f"登录过程中出现异常: {e}")
    finally:
        driver.quit()


def is_logged_in() -> bool:
    """检查是否已经完成过首次登录。"""
    return os.path.isfile(LOGIN_DONE_FLAG)


# ======================== 步骤5：截图 ========================

def take_video_screenshot(video_url: str, video_title: str):
    """
    启动 Chrome，访问视频页面，等待播放器加载后对播放器区域截图。
    如果已经登录过，默认使用 headless 静默模式。
    """
    # 决定是否使用 headless 模式
    use_headless = is_logged_in() and (not FORCE_SHOW_BROWSER)

    if use_headless:
        print("正在以后台静默模式启动 Chrome...")
    else:
        print("正在启动 Chrome 浏览器（窗口模式）...")

    options = build_chrome_options(headless=use_headless)
    service = Service(executable_path=CHROME_DRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, 20)

    try:
        print(f"正在访问视频页面: {video_url}")
        driver.get(video_url)

        print("等待播放器加载...")
        player_area = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "#bilibili-player, .bpx-player-video-wrap")
            )
        )

        print(f"播放器已加载，等待 {VIDEO_WAIT_SECONDS} 秒让画面呈现题目...")
        time.sleep(VIDEO_WAIT_SECONDS)

        # ★★★ 截图前清理：隐藏"已静音开播"提示、弹幕、底部控制栏等干扰元素 ★★★
        print("正在清理播放器浮层（静音提示、弹幕等）...")
        driver.execute_script("""
            // 要隐藏的元素选择器列表（可根据需要增减）
            const selectorsToHide = [
                '.bpx-player-toast-wrap',          // "已静音开播 点击恢复音量" 提示
                '.bpx-player-toast-row',            // 同上（备选选择器）
                '.bpx-player-dm-wrap',              // 弹幕层
                '.bpx-player-sending-bar',          // 底部弹幕发送栏
                '.bpx-player-control-wrap',         // 播放器底部控制条
                '.bpx-player-top-wrap',             // 播放器顶部标题栏
                '.bpx-player-dialog-wrap',          // 各种弹窗/对话框
                '.bpx-player-tooltip-area',         // 工具提示区域
                '.bpx-player-state-wrap',           // 播放状态提示（暂停图标等）
            ];
            selectorsToHide.forEach(selector => {
                document.querySelectorAll(selector).forEach(el => {
                    el.style.display = 'none';
                });
            });
        """)
        # 等一小会儿让 DOM 变更生效
        time.sleep(0.5)

        # 保存截图
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        safe_title = re.sub(r'[\\/*?:"<>|]', "", video_title)
        save_path = os.path.join(SCREENSHOT_DIR, f"{safe_title}.png")

        player_area.screenshot(save_path)
        print(f"🎉 截图成功！已保存到: {save_path}")

    except Exception as e:
        print(f"截图过程中发生异常: {e}")
    finally:
        print("关闭浏览器。")
        time.sleep(1)
        driver.quit()


# ======================== 主流程 ========================

def main():
    # 1. 通过 API 获取视频列表
    videos = fetch_video_list(MID, SEASON_ID)
    if not videos:
        print("无法获取视频列表，程序终止。")
        return

    # 2. 正则匹配找到最新的目标视频
    target = find_target_video(videos, TITLE_PATTERN)
    if not target:
        print("没有找到符合条件的视频，程序终止。")
        return

    # 3. 检查登录状态：首次运行需要手动登录一次
    if not is_logged_in():
        first_time_login()
        if not is_logged_in():
            print("未完成登录，程序终止。")
            return

    # 4. 截图（已登录则自动使用后台静默模式）
    take_video_screenshot(target["url"], target["title"])


if __name__ == "__main__":
    main()