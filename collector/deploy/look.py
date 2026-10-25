"""Debug: open a URL with the Instagram profile (no typing, no login) and print what the page shows.

    sudo -u earth ... python deploy/look.py [url]
"""
import sys

from eecollector.config import Settings
from eecollector.igweb import IGBrowser

url = sys.argv[1] if len(sys.argv) > 1 else "https://www.instagram.com/"
s = Settings()
with IGBrowser(s) as ig:
    ig.page.goto(url, wait_until="domcontentloaded")
    ig.page.wait_for_timeout(6000)
    print("url:", ig.page.url.split("?")[0], "| logged in:", ig.logged_in(),
          "| cookies:", sorted(ig.cookies()))
    print(ig.page.evaluate("document.body.innerText")[:1500])
    ig.screenshot(s.state_dir / "screenshots")
