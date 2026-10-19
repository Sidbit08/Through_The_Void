"""Real-browser smoke checks against a disposable Waitress server.

Run from the repository root with the optional browser dependencies installed.
No accounts, event times or progress in the real instance are modified.
"""
import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Chromium:
    def __init__(self, executable):
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(executable_path=executable, headless=True, args=["--no-sandbox"])
        self.page = self.browser.new_page(viewport={"width": 1366, "height": 768})
        self.external = []
        def handle(route):
            if not route.request.url.startswith("http://127.0.0.1:"):
                self.external.append(route.request.url)
                route.abort()
            else:
                route.continue_()
        self.page.route("**/*", handle)
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def goto(self, url):
        self.page.goto(url, wait_until="networkidle")

    def evaluate(self, body):
        return self.page.evaluate("() => {" + body + "}")

    def fill(self, selector, value):
        self.page.locator(selector).fill(value)

    def click(self, selector):
        self.page.locator(selector).click()
        self.page.wait_for_load_state("networkidle")

    def hover(self, selector):
        self.page.locator(selector).hover()

    def resize(self, width, height):
        self.page.set_viewport_size({"width": width, "height": height})

    def screenshot(self, path):
        self.page.screenshot(path=str(path))

    def select_all(self):
        self.page.keyboard.press("Control+a")

    def close(self):
        self.browser.close()
        self.playwright.stop()


class Firefox:
    def __init__(self, executable, driver):
        from selenium import webdriver
        from selenium.webdriver.common.proxy import Proxy, ProxyType
        from selenium.webdriver.firefox.service import Service
        from selenium.webdriver.firefox.remote_connection import FirefoxRemoteConnection
        from selenium.webdriver.remote.client_config import ClientConfig
        options = webdriver.FirefoxOptions()
        options.binary_location = executable
        options.add_argument("-headless")
        options.set_preference("network.proxy.type", 1)
        options.set_preference("network.proxy.http", "127.0.0.1")
        options.set_preference("network.proxy.http_port", 9)
        options.set_preference("network.proxy.ssl", "127.0.0.1")
        options.set_preference("network.proxy.ssl_port", 9)
        options.set_preference("network.proxy.no_proxies_on", "localhost, 127.0.0.1")
        options.set_preference("datareporting.healthreport.uploadEnabled", False)
        options.set_preference("toolkit.telemetry.enabled", False)
        self.service = Service(executable_path=driver, log_output=str(ROOT / 'test-results' / 'firefox' / 'driver.log'))
        self.service.start()
        direct = Proxy()
        direct.proxy_type = ProxyType.DIRECT
        client = ClientConfig(remote_server_addr=self.service.service_url, timeout=30, proxy=direct)
        executor = FirefoxRemoteConnection(self.service.service_url, client_config=client)
        try:
            self.browser = webdriver.Remote(command_executor=executor, options=options)
        except BaseException:
            self.service.stop()
            raise
        self.external = []
        self.errors = None  # Firefox console collection is not implemented here.
        self.resize(1366, 768)

    def goto(self, url):
        self.browser.get(url)

    def evaluate(self, body):
        return self.browser.execute_script("return (() => {" + body + "})();")

    def fill(self, selector, value):
        element = self.browser.find_element("css selector", selector)
        element.clear()
        element.send_keys(value)

    def click(self, selector):
        self.browser.find_element("css selector", selector).click()

    def hover(self, selector):
        from selenium.webdriver import ActionChains
        ActionChains(self.browser).move_to_element(self.browser.find_element("css selector", selector)).perform()

    def resize(self, width, height):
        self.browser.set_window_size(width, height)
        delta = self.evaluate("return [outerWidth-innerWidth,outerHeight-innerHeight]")
        self.browser.set_window_size(width + delta[0], height + delta[1])

    def screenshot(self, path):
        self.browser.save_screenshot(str(path))

    def select_all(self):
        from selenium.webdriver import ActionChains
        from selenium.webdriver.common.keys import Keys
        ActionChains(self.browser).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).perform()

    def close(self):
        self.browser.quit()
        self.service.stop()


def wait_for(check, seconds=8):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return
        time.sleep(.05)
    raise AssertionError("Browser condition did not become true")


def check(browser, url, out, organizer_password):
    from void_app.puzzles import ANSWERS, STAGES
    b = browser
    b.goto(url + "/entry")
    b.screenshot(out / "entry.png")
    b.goto(url + "/organizer/login")
    b.fill('[name="identity"]', "browser-organizer")
    b.fill('[name="password"]', organizer_password)
    b.click('button.primary')
    wait_for(lambda: b.evaluate("return location.pathname === '/organizer'"))
    b.fill('input[name="participant"]', "browser-player")
    b.click('form.stack button')
    access = b.evaluate("return document.querySelector('.issued-code code').textContent")
    b.click('button.primary')
    wait_for(lambda: b.evaluate("return document.body.textContent.includes('Event in progress')"))
    b.goto(url + "/entry")
    b.fill('[name="identity"]', "browser-player")
    b.fill('[name="password"]', access)
    b.click('button.primary')
    wait_for(lambda: b.evaluate("return location.pathname === '/index.htm'"))
    b.click('#sound-control')
    sound_deadline=time.monotonic()+2
    while time.monotonic()<sound_deadline and not b.evaluate("return document.querySelector('#sound-control').textContent === 'Mute sound'"):
        time.sleep(.05)
    if b.evaluate("return document.querySelector('#sound-control').textContent === 'Mute sound'"):
        sound_mode="audio context running; mute toggled successfully (physical output not checked)"
        b.click('#sound-control')
        wait_for(lambda: b.evaluate("return document.querySelector('#sound-control').textContent === 'Enable sound'"))
    else:
        sound_mode="audio unavailable or browser-blocked; Enable sound control remains truthful"
        assert b.evaluate("return document.querySelector('#sound-control').textContent === 'Enable sound' && document.querySelector('#sound-control').getAttribute('aria-pressed') === 'false'")
    for width, height in [(1366,768),(1024,768),(800,600),(1920,1080)]:
        b.resize(width, height)
        assert b.evaluate("const i=document.querySelector('.puzzle-image').getBoundingClientRect(),h=document.querySelector('.door').getBoundingClientRect();return h.left>=i.left && h.top>=i.top && h.right<=i.right && h.bottom<=i.bottom;")
    b.resize(1366,768)
    b.screenshot(out / "home.png")
    b.click('.door')
    wait_for(lambda: b.evaluate("return location.pathname === '/level1.htm'"))
    for width, height in [(1366,768),(1024,768),(800,600),(1920,1080)]:
        b.resize(width, height)
        b.hover('.white-spot')
        assert b.evaluate("return getComputedStyle(document.querySelector('.white-spot'),'::after').content.includes('Username- TheLesser')")
        geometry=b.evaluate("const i=document.querySelector('.puzzle-image').getBoundingClientRect(),h=document.querySelector('.white-spot').getBoundingClientRect(),f=document.querySelector('.art-frame').getBoundingClientRect();return {x:(h.left-i.left)/i.width,y:(h.top-i.top)/i.height,image:[i.width,i.height],frame:[f.width,f.height]}")
        assert abs(geometry['x']-.578)<.002 and abs(geometry['y']-.308)<.002, (width,height,geometry)
    b.resize(1366,768)
    b.hover('.white-spot')
    b.screenshot(out / "level1-hover.png")
    measurements = []
    for stage in range(2,9):
        b.goto(url + STAGES[stage][0])
        if stage == 2:
            b.fill('[name="username"]', "incorrect")
            b.fill('[name="password"]', "incorrect")
            b.click('button.primary')
            assert b.evaluate("return document.body.textContent.includes('ERROR 404: Wrong input provided.')")
            b.screenshot(out / "wrong-input.png")
        user, password = ANSWERS[stage]
        b.fill('[name="username"]', user)
        b.fill('[name="password"]', password)
        b.click('button.primary')
        wait_for(lambda: b.evaluate("return !!document.querySelector('.puzzle-image') && document.querySelector('.puzzle-image').complete"))
        for width, height in [(1366,768),(1024,768),(800,600),(1920,1080)]:
            b.resize(width,height)
            sizes = b.evaluate("const i=document.querySelector('.puzzle-image').getBoundingClientRect();return {width:innerWidth,height:innerHeight,scroll:document.documentElement.scrollHeight,bottom:i.bottom,right:i.right,left:i.left,naturalWidth:document.querySelector('.puzzle-image').naturalWidth}")
            assert sizes['left'] >= 0 and sizes['right'] <= width + 1, (stage,sizes)
            assert sizes['bottom'] <= height - 30, (stage,sizes)
            if stage != 2:
                assert sizes['scroll'] <= height + 1, (stage,sizes)
            measurements.append({"stage":stage,**sizes})
        b.resize(1366,768)
        b.screenshot(out / f"stage-{stage}.png")
        if stage == 2:
            assert b.evaluate("return getComputedStyle(document.body).backgroundColor === 'rgb(0, 0, 0)'")
            assert b.evaluate("return document.querySelector('.buried-text').getBoundingClientRect().top > innerHeight")
            b.select_all()
            assert b.evaluate("return getSelection().toString().includes('TheBrightest.htm')")
            b.evaluate("document.querySelector('.buried-text').scrollIntoView();")
            b.screenshot(out / "level2-selected.png")
        if stage == 7:
            b.goto(url + "/scrambled.htm")
            assert b.evaluate("return document.querySelector('.binary-text').textContent.split(' ').length === 30")
            b.screenshot(out / "helper.png")
        assert b.evaluate("return performance.getEntriesByType('resource').every(r=>new URL(r.name).origin === location.origin)")
    b.goto(url + "/organizer")
    assert b.evaluate("return document.querySelector('tbody').textContent.includes('browser-player')")
    b.screenshot(out / "organizer.png")
    assert not b.external, b.external
    assert not b.errors, b.errors
    return {"result":"passed", "measurements": measurements, "external_page_requests":b.external,"javascript_errors":b.errors,"sound_check":sound_mode}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--engine",choices=["chromium","firefox"],default="chromium")
    parser.add_argument("--executable",default="/usr/bin/chromium")
    parser.add_argument("--driver",default="geckodriver")
    parser.add_argument("--port",type=int,default=8081)
    args=parser.parse_args()
    from werkzeug.security import generate_password_hash
    from void_app import create_app
    from void_app.db import connect
    out=ROOT / "test-results" / args.engine
    out.mkdir(parents=True,exist_ok=True)
    for name in ("result.json", "failure.png"):
        (out / name).unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="void-browser-") as temporary:
        data=Path(temporary)
        shutil.copytree(ROOT / "instance" / "assets",data / "assets")
        for name in ("hotspots.json","asset-report.json"):
            shutil.copy(ROOT / "instance" / name,data / name)
        app=create_app({"DATA_DIR":data})
        password=secrets.token_urlsafe(24)
        with connect(app.config["DATABASE"]) as db:
            db.execute("INSERT INTO organizers(username,password_hash) VALUES(?,?)",("browser-organizer",generate_password_hash(password)))
        env=os.environ.copy()
        env["VOID_DATA_DIR"]=str(data)
        url=f"http://127.0.0.1:{args.port}"
        with (out / "server.log").open("w") as log:
            server=subprocess.Popen([sys.executable,str(ROOT / "manage.py"),"serve","--port",str(args.port)],env=env,stdout=log,stderr=log)
            browser=None
            try:
                def ready():
                    try:
                        with urllib.request.urlopen(url + "/entry",timeout=1) as response:
                            return response.status == 200
                    except OSError:
                        return False
                wait_for(ready)
                browser=Chromium(args.executable) if args.engine=="chromium" else Firefox(args.executable,args.driver)
                result=check(browser,url,out,password)
                (out / "result.json").write_text(json.dumps(result,indent=2))
                print(f"{args.engine}: passed full browser progression, responsive hotspots, layouts, select-all clue, sound controls and organizer UI")
            except Exception:
                if browser:
                    browser.screenshot(out / "failure.png")
                raise
            finally:
                if browser:
                    browser.close()
                server.terminate()
                server.wait(timeout=10)


if __name__=="__main__":
    main()
