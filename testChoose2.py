"""
B站合集视频截图工具 — 交互版 (时间过滤 + 防风控终极版)

功能：
1. 全程使用 Selenium 模拟真实用户浏览（100% 绕过风控，无需 API）
2. 自动在UP主个人空间翻页，查找所有匹配正则的视频（支持时间过滤）
3. 用户输入关键字，从筛选结果中定位视频
4. 用户输入截图秒数，截取指定时刻的画面
5. 全程复用同一个浏览器实例，速度快且稳定

使用场景：批量截图后，个别视频默认秒数截不到好画面，用此脚本单独补截。

依赖：pip install selenium
"""

import re
import os
import time
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options as ChromeOptions


# ======================== 配置区 ========================

# B站用户 mid
MID = "688379639"

# 视频标题匹配规则
TITLE_PATTERN = re.compile(r"27考研.*题")

# ★★★ 最早检查日期（遇到比这个日期更早的视频，直接停止查找）★★★
TARGET_DATE_STR = "2025-11-01"
TARGET_DATE = datetime.strptime(TARGET_DATE_STR, "%Y-%m-%d")

# ChromeDriver 路径
CHROME_DRIVER_PATH = r"C:\Users\LiGuangxiao\Desktop\chromedriver.exe"

# Selenium 专用的用户数据目录
SELENIUM_PROFILE_DIR = r"C:\Users\LiGuangxiao\AppData\Local\Google\Chrome\SeleniumProfile"

# 登录完成的标记文件
LOGIN_DONE_FLAG = os.path.join(SELENIUM_PROFILE_DIR, ".bilibili_logged_in")

# 截图保存目录
SCREENSHOT_DIR = "bilibili_screenshots"

# 是否强制显示浏览器窗口（设为 True 则每次都弹出窗口，方便调试）
FORCE_SHOW_BROWSER = False


# ======================== 辅助函数 ========================

def parse_bili_date(date_str: str) -> datetime:
    """解析 B站的日期字符串为 datetime 对象"""
    date_str = date_str.strip()
    now = datetime.now()
    try:
        if any(x in date_str for x in["秒", "分", "时", "刚刚"]):
            return now
        elif "昨天" in date_str:
            return now - timedelta(days=1)
        elif "前天" in date_str:
            return now - timedelta(days=2)
        elif date_str.count("-") == 1:
            month, day = map(int, date_str.split("-"))
            return datetime(now.year, month, day)
        elif date_str.count("-") == 2:
            return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        pass
    return now

def build_chrome_options(headless: bool = False) -> ChromeOptions:
    options = ChromeOptions()
    options.add_argument("--mute-audio")
    options.add_argument("--remote-allow-origins=*")
    options.add_argument(f"--user-data-dir={SELENIUM_PROFILE_DIR}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--disable-extensions")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")

    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")

    return options

def is_logged_in() -> bool:
    return os.path.isfile(LOGIN_DONE_FLAG)

def first_time_login():
    print("=" * 60)
    print("【首次运行】需要登录B站账号以获取高清画质")
    print("  浏览器即将打开B站登录页面，请手动完成登录。")
    print("  登录成功后，回到此窗口按 Enter 键继续。")
    print("=" * 60)

    os.makedirs(SELENIUM_PROFILE_DIR, exist_ok=True)

    options = build_chrome_options(headless=False)
    service = Service(executable_path=CHROME_DRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.get("https://passport.bilibili.com/login")
        print("\n⏳ 等待您在浏览器中登录...")
        input(">>> 登录完成后，请回到这个命令行窗口按 Enter 键...")

        driver.get("https://www.bilibili.com")
        time.sleep(2)

        with open(LOGIN_DONE_FLAG, "w", encoding="utf-8") as f:
            f.write(f"logged_in_at={time.strftime('%Y-%m-%d %H:%M:%S')}\n")

        print("✅ 登录状态已保存！后续运行将自动使用此账号，浏览器在后台静默运行。\n")
    except Exception as e:
        print(f"登录过程中出现异常: {e}")
    finally:
        driver.quit()


# ======================== 核心逻辑 1：查找所有目标视频 ========================

def find_all_target_videos(driver: webdriver.Chrome, mid: str, pattern: re.Pattern) -> list[dict]:
    """
    使用 Selenium 在UP主空间翻页查找所有匹配的视频，并检查日期。
    """
    url = f"https://space.bilibili.com/{mid}/video"
    print(f"正在访问UP主视频页: {url}")
    driver.get(url)
    
    page = 1
    max_pages = 50 # 防止死循环
    reached_old_videos = False
    matched_videos =[]
    seen_urls = set() # 用于去重
    
    while page <= max_pages:
        print(f"正在扫描第 {page} 页...")
        time.sleep(3) # 等待页面和视频列表加载
        
        # 滚动页面到底部，触发图片和元素的懒加载
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)
        
        # 查找所有视频卡片容器
        cards = driver.find_elements(By.CSS_SELECTOR, ".bili-video-card")
        
        for card in cards:
            try:
                # 1. 精准定位到包含真实标题的 div 元素
                title_div = card.find_element(By.CSS_SELECTOR, ".bili-video-card__title")
                title = title_div.get_attribute("title")
                if not title:
                    title = title_div.text
                title = title.strip()

                a_tag = title_div.find_element(By.TAG_NAME, "a")
                href = a_tag.get_attribute("href").split('?')[0]

                # 2. 获取日期并判断
                try:
                    date_span = card.find_element(By.CSS_SELECTOR, ".bili-video-card__subtitle span")
                    date_str = date_span.text.strip()
                except:
                    date_str = ""
                    
                if date_str:
                    video_date = parse_bili_date(date_str)
                    # 如果视频发布时间早于设定的目标时间，直接停止查找
                    if video_date < TARGET_DATE:
                        print(f"  [跳过] 视频《{title}》发布于 {date_str}，早于 {TARGET_DATE_STR}，停止往前查找。")
                        reached_old_videos = True
                        break # 跳出当前页的卡片遍历
                
                # 3. 检查标题是否匹配正则，且未被记录过
                if pattern.search(title) and href not in seen_urls:
                    matched_videos.append({"title": title, "url": href})
                    seen_urls.add(href)
                    
            except Exception:
                continue
                
        # 如果已经遇到老视频，直接结束整个翻页循环
        if reached_old_videos:
            break
            
        # 尝试点击下一页
        try:
            next_btn = driver.find_element(By.XPATH, "//button[contains(@class, 'vui_pagenation--btn-side') and contains(text(), '下一页')]")
            
            btn_class = next_btn.get_attribute("class")
            if next_btn.get_attribute("disabled") or "disabled" in btn_class:
                print("已到达最后一页。")
                break
                
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
            time.sleep(0.5)
            next_btn.click()
            page += 1
        except Exception:
            print("未找到下一页按钮，或已到达最后一页。")
            break
            
    return matched_videos


# ======================== 核心逻辑 2：指定秒数截图 ========================

CLEANUP_JS = """
    var video = document.querySelector('video');
    if (video) { video.volume = 0.01; }
    const hide =[
        '.bpx-player-toast-wrap', '.bpx-player-toast-row',
        '.bpx-player-dm-wrap', '.bpx-player-sending-bar',
        '.bpx-player-control-wrap', '.bpx-player-top-wrap',
        '.bpx-player-dialog-wrap', '.bpx-player-tooltip-area',
        '.bpx-player-state-wrap',
    ];
    hide.forEach(s => {
        document.querySelectorAll(s).forEach(el => { if(el) el.style.display = 'none'; });
    });
"""

def take_specific_screenshot(driver: webdriver.Chrome, target: dict, target_sec: float):
    """跳转到指定视频的指定秒数并截图"""
    wait = WebDriverWait(driver, 20)
    
    try:
        print(f"\n正在访问视频页面: {target['url']}")
        driver.get(target["url"])

        player_area = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "#bilibili-player, .bpx-player-video-wrap")
            )
        )

        # 等待视频元素就绪
        time.sleep(3)

        # 跳转到指定秒数并暂停
        print(f"正在跳转到第 {target_sec} 秒...")
        driver.execute_script(f"""
            var video = document.querySelector('video');
            if (video) {{
                video.currentTime = {target_sec};
                video.pause();
            }}
        """)
        time.sleep(1.5)

        # 清理浮层
        driver.execute_script(CLEANUP_JS)
        time.sleep(0.5)

        # 截图保存
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        safe_title = re.sub(r'[\\/*?:"<>|]', "", target["title"])
        save_path = os.path.join(SCREENSHOT_DIR, f"{safe_title}.png")

        player_area.screenshot(save_path)
        print(f"\n🎉 截图成功！第 {target_sec} 秒，已保存到: {save_path}")

    except Exception as e:
        print(f"截图过程中发生异常: {e}")


# ======================== 主流程 ========================

def main():
    # 1. 检查登录状态
    if not is_logged_in():
        first_time_login()
        if not is_logged_in():
            print("未完成登录，程序终止。")
            return

    # 2. 启动浏览器（复用同一个实例进行查找和截图）
    use_headless = is_logged_in() and (not FORCE_SHOW_BROWSER)
    if use_headless:
        print("正在以后台静默模式启动 Chrome...")
    else:
        print("正在启动 Chrome 浏览器（窗口模式）...")

    options = build_chrome_options(headless=use_headless)
    service = Service(executable_path=CHROME_DRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)

    try:
        # 3. 查找所有目标视频
        matched = find_all_target_videos(driver, MID, TITLE_PATTERN)
        if not matched:
            print("没有找到符合条件的视频，程序终止。")
            return

        print(f"\n共匹配到 {len(matched)} 个目标视频。\n")

        # 4. 用户输入关键字定位视频
        keyword = input("🔍 输入标题关键字（如 96题）: ").strip()
        if not keyword:
            print("未输入关键字，程序终止。")
            return

        results = [v for v in matched if keyword in v["title"]]

        if not results:
            print(f"未找到标题包含「{keyword}」的视频，程序终止。")
            return

        # 如果关键字匹配到多个，让用户选择
        if len(results) == 1:
            target = results[0]
        else:
            print(f"\n找到 {len(results)} 个匹配视频：")
            for i, v in enumerate(results, 1):
                print(f"  {i}. {v['title']}")
            choice = input(f"\n输入编号选择 (1-{len(results)}): ").strip()
            try:
                target = results[int(choice) - 1]
            except (ValueError, IndexError):
                print("无效的编号，程序终止。")
                return

        print(f"\n已选择: 《{target['title']}》")

        # 5. 用户输入截图秒数
        sec_input = input("⏱️  输入截图秒数（如 2、5.5）: ").strip()
        try:
            target_sec = float(sec_input)
        except ValueError:
            print("无效的秒数，程序终止。")
            return

        # 6. 执行截图
        take_specific_screenshot(driver, target, target_sec)

    finally:
        print("\n关闭浏览器。")
        time.sleep(1)
        driver.quit()


if __name__ == "__main__":
    main()