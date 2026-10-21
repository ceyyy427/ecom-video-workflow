"""Regression: held dashboard response must never display under another account."""

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx
from playwright.async_api import async_playwright


async def main(url):
    async with httpx.AsyncClient(base_url=url) as client:
        client.headers["X-Workflow-Token"] = (await client.get("/api/session")).json()["token"]
        ids = []
        for index, spend in enumerate([111, 222]):
            account = (
                await client.post(
                    "/api/distribution/accounts",
                    json={
                        "name": f"并发验收 {index}",
                        "platform": "qianchuan",
                        "advertiser_id": str(time.time_ns()),
                    },
                )
            ).json()
            ids.append(account["id"])
            raw = f"date,material_id,spend,impressions,clicks,orders,revenue,video_views,completed_views\n2026-10-01,123,{spend},1000,20,2,500,100,10\n".encode()
            response = await client.post(
                "/api/reports/import",
                data={
                    "account_id": account["id"],
                    "start_date": "2026-10-01",
                    "end_date": "2026-10-01",
                    "actor": "延迟请求测试",
                    "confirmed": "true",
                },
                files={"file": ("fixture.csv", raw, "text/csv")},
            )
            response.raise_for_status()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url + "/distribution")
        await page.wait_for_function('()=>!document.querySelector("#filterForm button").disabled')
        await page.locator("#account").select_option(ids[0])
        await page.wait_for_function('()=>!document.querySelector("#filterForm button").disabled')
        await page.locator("#startDate").fill("2026-10-01")
        await page.locator("#endDate").fill("2026-10-01")
        await page.locator("#filterForm button").click()
        await page.wait_for_function(
            '()=>document.querySelector("#kpis strong").textContent==="111"'
        )
        await page.wait_for_function('()=>!document.querySelector("#filterForm button").disabled')
        pending, release = asyncio.Event(), asyncio.Event()

        async def hold(route):
            pending.set()
            await release.wait()
            await route.continue_()

        await page.route("**/api/reports/dashboard?**", hold)
        try:
            await page.locator("#filterForm button").click()
            await asyncio.wait_for(pending.wait(), 5)
            assert await page.locator("#account").is_disabled(), (
                "Account remains editable while previous-account response is pending"
            )
            assert await page.locator("#startDate").is_disabled()
            assert await page.locator("#endDate").is_disabled()
        finally:
            release.set()
        await page.wait_for_function('()=>!document.querySelector("#account").disabled')
        await page.unroute("**/api/reports/dashboard?**", hold)
        await page.locator("#account").select_option(ids[1])
        await page.wait_for_function(
            '()=>document.querySelector("#kpis strong").textContent==="222"'
        )
        assert await page.locator("#account").input_value() == ids[1]
        assert ids[1] in await page.locator("#exportReview").get_attribute("href")
        await browser.close()
    result = {
        "passed": True,
        "fixture_only": True,
        "checks": [
            "context_controls_locked_during_pending_response",
            "next_account_dashboard_matches_selector",
            "export_matches_account",
        ],
    }
    Path("docs/evidence/p2/account-guard.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8766")
    asyncio.run(main(parser.parse_args().url))
