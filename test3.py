"""
B站UP主所有视频截图工具 (精准匹配版 v7)

功能：
1. 全程使用 Selenium 模拟真实用户浏览（100% 绕过风控）
2. 自动在UP主个人空间翻页查找匹配正则的视频
3. 支持时间过滤：只检查指定日期（如 2025-11-01）之后的视频，遇到老视频自动停止
4. 【修复】精准提取视频标题，解决误抓取播放量/时长导致正则匹配失败的问题
5. 首次运行弹出浏览器让用户登录B站，后续运行后台静默截图

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

# 最早检查日期（遇到比这个日期更早的视频，直接停止查找）
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

# 视频加载后等待秒数（等视频画面出现题目）
VIDEO_WAIT_SECONDS = 2

# 是否强制显示浏览器窗口（设为 True 则每次都弹出窗口，方便调试）
FORCE_SHOW_BROWSER = False


# ======================== 核心逻辑 ========================

def parse_bili_date(date_str: str) -> datetime:
    """
    解析 B站的日期字符串为 datetime 对象
    """
    date_str = date_str.strip()
    now = datetime.now()
    try:
        if any(x in date_str for x in ["秒", "分", "时", "刚刚"]):
            return now
        elif "昨天" in date_str:
            return now - timedelta(days=1)
        elif "前天" in date_str:
            return now - timedelta(days=2)
        elif date_str.count("-") == 1:
            # 格式如 "10-20"，代表今年
            month, day = map(int, date_str.split("-"))
            return datetime(now.year, month, day)
        elif date_str.count("-") == 2:
            # 格式如 "2025-10-20"，代表往年
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
        print("   登录完成后，请回到这个命令行窗口按 Enter 键。\n")

        input(">>> 按 Enter 键确认已登录完成...")

        driver.get("https://www.bilibili.com")
        time.sleep(2)

        with open(LOGIN_DONE_FLAG, "w", encoding="utf-8") as f:
            f.write(f"logged_in_at={time.strftime('%Y-%m-%d %H:%M:%S')}\n")

        print("✅ 登录状态已保存！后续运行将自动使用此账号，浏览器在后台静默运行。\n")

    except Exception as e:
        print(f"登录过程中出现异常: {e}")
    finally:
        driver.quit()

def find_target_video(driver: webdriver.Chrome, mid: str, pattern: re.Pattern) -> dict | None:
    """
    使用 Selenium 在UP主空间翻页查找匹配的视频，并检查日期。
    """
    url = f"https://space.bilibili.com/{mid}/video"
    print(f"正在访问UP主视频页: {url}")
    driver.get(url)
    
    page = 1
    max_pages = 50 # 防止死循环
    reached_old_videos = False
    
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
                # 1. 【修复点】精准定位到包含真实标题的 div 元素
                title_div = card.find_element(By.CSS_SELECTOR, ".bili-video-card__title")
                
                # 优先从 title 属性获取完整标题，如果没有则获取文本
                title = title_div.get_attribute("title")
                if not title:
                    title = title_div.text
                title = title.strip()

                # 从标题 div 内部的 a 标签获取链接
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
                        print(f"[跳过] 视频《{title}》发布于 {date_str}，早于 {TARGET_DATE_STR}，停止往前查找。")
                        reached_old_videos = True
                        break # 跳出当前页的卡片遍历
                
                # 3. 检查标题是否匹配正则
                if pattern.search(title):
                    print(f"  ✅ 匹配成功: 《{title}》 (发布于 {date_str})")
                    print(f"     链接: {href}\n")
                    return {"title": title, "url": href}
                    
            except Exception as e:
                # 如果某个卡片解析失败，跳过继续解析下一个
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
        except Exception as e:
            print("未找到下一页按钮，或已到达最后一页。")
            break
            
    return None

def take_video_screenshot(driver: webdriver.Chrome, video_url: str, video_title: str):
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

        print("正在清理播放器浮层（静音提示、弹幕等）...")
        driver.execute_script("""
            const selectorsToHide =[
                '.bpx-player-toast-wrap',
                '.bpx-player-toast-row',
                '.bpx-player-dm-wrap',
                '.bpx-player-sending-bar',
                '.bpx-player-control-wrap',
                '.bpx-player-top-wrap',
                '.bpx-player-dialog-wrap',
                '.bpx-player-tooltip-area',
                '.bpx-player-state-wrap',
            ];
            selectorsToHide.forEach(selector => {
                document.querySelectorAll(selector).forEach(el => {
                    if(el) el.style.display = 'none';
                });
            });
        """)
        time.sleep(0.5)

        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        safe_title = re.sub(r'[\\/*?:"<>|]', "", video_title)
        save_path = os.path.join(SCREENSHOT_DIR, f"{safe_title}.png")

        player_area.screenshot(save_path)
        print(f"🎉 截图成功！已保存到: {save_path}")

    except Exception as e:
        print(f"截图过程中发生异常: {e}")

# ======================== 主流程 ========================

def main():
    if not is_logged_in():
        first_time_login()
        if not is_logged_in():
            print("未完成登录，程序终止。")
            return

    use_headless = is_logged_in() and (not FORCE_SHOW_BROWSER)
    if use_headless:
        print("正在以后台静默模式启动 Chrome...")
    else:
        print("正在启动 Chrome 浏览器（窗口模式）...")

    options = build_chrome_options(headless=use_headless)
    service = Service(executable_path=CHROME_DRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)

    try:
        target = find_target_video(driver, MID, TITLE_PATTERN)
        if not target:
            print("没有找到符合条件的视频，程序终止。")
            return

        take_video_screenshot(driver, target["url"], target["title"])
        
    finally:
        print("关闭浏览器。")
        time.sleep(1)
        driver.quit()

if __name__ == "__main__":
    main()