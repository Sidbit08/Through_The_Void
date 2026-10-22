"""Optional Firefox policy check in a copied browser and disposable profile.

No /etc policy or normal browser profile is changed. Selenium and geckodriver
are development-only dependencies, not toolkit prerequisites.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from ctfmode import config, render


def subset(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and subset(value, actual[key]) for key, value in expected.items())
    return expected == actual


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--firefox-directory', type=Path, required=True)
    parser.add_argument('--executable', default='firefox-esr')
    parser.add_argument('--driver', required=True)
    parser.add_argument('--version', default='153.5')
    args = parser.parse_args()
    from selenium import webdriver
    from selenium.webdriver.firefox.service import Service
    from selenium.webdriver.common.proxy import Proxy, ProxyType
    from selenium.webdriver.firefox.remote_connection import FirefoxRemoteConnection
    from selenium.webdriver.remote.client_config import ClientConfig
    out = TOOL / 'test-results'
    out.mkdir(exist_ok=True)
    result_path = out/'firefox-policy.json'
    result_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix='ctf-policy-browser-') as temporary:
        root = Path(temporary)
        browser_dir = root/'firefox'
        shutil.copytree(args.firefox_directory, browser_dir, symlinks=False, ignore_dangling_symlinks=True)
        settings = config.load(TOOL/'examples/event.json')
        policies = render.firefox(settings, tuple(map(int,args.version.split('.')[:2])))
        directory = browser_dir/'distribution'
        directory.mkdir(exist_ok=True)
        (directory/'policies.json').write_text(json.dumps({'policies': policies}))
        options = webdriver.FirefoxOptions()
        options.binary_location = str(browser_dir/args.executable)
        options.add_argument('-headless')
        options.set_preference('datareporting.healthreport.uploadEnabled', False)
        options.set_preference('toolkit.telemetry.enabled', False)
        service = Service(args.driver, service_args=['--allow-system-access'], log_output=str(out/'firefox-driver.log'))
        service.start()
        direct = Proxy();direct.proxy_type = ProxyType.DIRECT
        client_config = ClientConfig(remote_server_addr=service.service_url, proxy=direct)
        connection = FirefoxRemoteConnection(remote_server_addr=service.service_url, keep_alive=True, ignore_proxy=True, client_config=client_config)
        browser = None
        try:
            browser = webdriver.Remote(command_executor=connection, options=options)
            browser.execute('SET_CONTEXT', {'context': 'chrome'})
            actual = json.loads(browser.execute_script('return JSON.stringify(Services.policies.getActivePolicies());'))
            assert subset(policies, actual), actual
            checks = browser.execute_script('''return {
              dohLocked: Services.prefs.prefIsLocked('network.trr.mode'),
              dohDisabled: Services.prefs.getIntPref('network.trr.mode') === 5,
              proxyLocked: Services.prefs.prefIsLocked('network.proxy.type'),
              proxyManual: Services.prefs.getIntPref('network.proxy.type') === 1,
              devtoolsAllowed: Services.policies.isAllowed('devtools'),
              chatbotDisabled: !Services.prefs.getBoolPref('browser.ml.chat.enabled'),
              chatbotLocked: Services.prefs.prefIsLocked('browser.ml.chat.enabled')
            };''')
            assert all(checks.values()), checks
            result_path.write_text(json.dumps({'result': 'passed', 'checks': checks,
                                              'scope': 'copied Firefox, disposable profile; real lab policy conflicts/other browser versions remain pilot checks'},indent=2)+'\n')
            print('Firefox: generated policies active; proxy/DoH/chatbot locked; DevTools available')
        finally:
            if browser: browser.quit()
            service.stop()


if __name__ == '__main__':
    main()
