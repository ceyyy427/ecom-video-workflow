"""Local headless page regression; touches only an explicitly marked engineering copy."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--engineering-copy", action="store_true")
    parser.add_argument("--run-name", choices=["ui-acceptance", "ui-contrast-red", "ui-final"], default="ui-acceptance")
    args = parser.parse_args()
    work = args.workspace.resolve()
    if not args.engineering_copy or not (work / "runtime/workflow.db").is_file():
        parser.error("只允许仓库外明确指定的工程数据副本")
    output = work / args.run_name
    output.mkdir(exist_ok=False)
    sample = output / "market.csv"
    sample.write_text("sku,product_name,price,currency,sampled_at,source\nA01,软壳衣,399,CNY,2026-10-28,授权工程样本第1行\nA02,软壳衣,,CNY,2026-10-28,授权工程样本第2行\n")
    base = f"http://127.0.0.1:{args.port}"
    errors, external, approval_requests, failed_api = [], [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})

        def guard(route):
            req = route.request
            if urlsplit(req.url).hostname not in ("127.0.0.1", "localhost"):
                external.append(req.url)
                return route.abort()
            if req.method not in ("GET", "HEAD") and any(s in req.url for s in ("/facts/confirm", "/scripts/confirm", "/style-reviews", "/alignments/", "/review", "/iterations")):
                approval_requests.append(req.url)
                return route.abort()
            route.continue_()

        context.route("**/*", guard)
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("response", lambda r: failed_api.append({"url": r.url, "status": r.status}) if "/api/" in r.url and r.status >= 400 else None)
        page.goto(base + "/operations", wait_until="networkidle")
        page.locator("#opsState").filter(has_text="先选择商品").wait_for()
        colors = page.locator(".ops-header a.ops-primary").evaluate("(e)=>{const s=getComputedStyle(e);return [s.color,s.backgroundColor]}")
        import re
        def luminance(css):
            numbers = [int(n) / 255 for n in re.findall(r"\d+", css)[:3]]
            values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in numbers]
            return sum(v * weight for v, weight in zip(values, (.2126, .7152, .0722), strict=True))
        lights = sorted(luminance(c) for c in colors)
        assert (lights[1] + .05) / (lights[0] + .05) >= 4.5, ("primary contrast", colors)
        assert page.get_by_role("tab").count() == 7
        for tab in page.get_by_role("tab").all():
            tab.click()
            assert page.locator('[role="tabpanel"]:visible').count() == 1
        page.get_by_role("tab", name="市场资料", exact=True).click()
        form = page.locator("#marketForm")
        form.locator('[name="file"]').set_input_files(sample)
        form.locator('[name="declared_scope"]').fill("AUTOMATED FIXTURE UI authorized samples, not customer data or market-wide estimate")
        form.get_by_role("button", name="分析这份样本", exact=True).click()
        page.locator("#opsState").filter(has_text="本机记录已保存").wait_for()
        assert "399" in page.locator("#opsResults").inner_text()
        assert "缺价 1 条" in page.locator("#opsResults").inner_text()
        for width in (1440, 768, 390):
            page.set_viewport_size({"width": width, "height": 1000})
            page.screenshot(path=str(output / f"operations-{width}.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"horizontal overflow {width}"
        page.set_viewport_size({"width": 1440, "height": 1000})
        first = page.get_by_role("tab", name="市场资料", exact=True)
        first.focus()
        page.keyboard.press("ArrowRight")
        assert page.get_by_role("tab", name="商品定位", exact=True).get_attribute("aria-selected") == "true"
        # No customer approval action is performed. Inspect all empty/disabled states.
        assert page.locator("#strategyForm button").is_disabled()
        page.locator("details.ops-connections > summary").click()
        account = page.locator("#accountForm")
        account.locator('[name="name"]').fill("AUTOMATED FIXTURE UI 报表账户")
        account.locator('[name="subject"]').fill("fixture-owned-account")
        account.get_by_role("button").click()
        page.locator("#opsState").filter(has_text="本机记录已保存").wait_for()
        assert page.locator("#sourceForm [name=account_id] option").count() >= 2
        page.locator("details.ops-connections details > summary").click()
        assert page.locator("#oauthStartForm button").is_disabled()
        assert page.locator("#officialReadForm button").is_disabled()
        assert page.locator("#oauthConfigForm [name=client_secret]").input_value() == ""
        context.close()
        browser.close()
    result = {"local_page_qa": True, "widths": [1440, 768, 390], "seven_modules": True,
        "real_market_form": "passed; zero/missing preserved", "official_reads_disabled": True,
        "new_customer_approvals": 0, "platform_writes": 0, "external_requests": external,
        "page_errors": errors, "approval_requests": approval_requests, "failed_api": failed_api}
    (output / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    assert not errors and not external and not approval_requests and not failed_api, result
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
