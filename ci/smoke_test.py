"""Talk to a running Snacky container the way the chat assistant and a browser do.

Standard library only, so the CI runner needs no install step. Usage:
    smoke_test.py MCP_URL WEB_URL
Exits non-zero with a message on the first failed check.
"""

import json
import sys
import time
import urllib.error
import urllib.request

EXPECTED_TOOLS = {
    "search_food",
    "log_food",
    "log_barcode",
    "log_label",
    "log_recipe_portion",
    "log_estimate",
    "day_summary",
    "week_summary",
    "update_entry",
    "delete_entry",
    "set_goal",
    "add_serving",
    "suggest_foods",
    "log_again",
    "recipe_nutrition",
}


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def http(url: str, body: dict | None = None, timeout: float = 10) -> tuple[int, str]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    request = urllib.request.Request(url, data=data, headers=headers if body else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


_ids = iter(range(1, 1000))


def rpc(mcp_url: str, method: str, params: dict | None = None) -> dict:
    status, text = http(
        f"{mcp_url}/mcp", {"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": params or {}}
    )
    if status != 200:
        fail(f"{method} answered {status}: {text[:200]}")
    reply = json.loads(text)
    if "error" in reply:
        fail(f"{method} returned an error: {reply['error']}")
    return reply["result"]


def call(mcp_url: str, tool: str, **arguments) -> dict:
    result = rpc(mcp_url, "tools/call", {"name": tool, "arguments": arguments})
    text = result["content"][0]["text"]
    if result.get("isError"):
        fail(f"{tool} failed: {text[:200]}")
    return json.loads(text)


def web_present(web_url: str) -> bool:
    """True when something listens on the web port. The entry point serves MCP
    only until the web app exists, and the check then has nothing to test."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            http(f"{web_url}/health", timeout=2)
        except OSError:
            time.sleep(0.5)
        else:
            return True
    return False


def main(mcp_url: str, web_url: str) -> None:
    result = rpc(
        mcp_url,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "smoke-test", "version": "0"},
        },
    )
    print("initialize:", result["serverInfo"]["name"])

    names = {t["name"] for t in rpc(mcp_url, "tools/list")["tools"]}
    if missing := EXPECTED_TOOLS - names:
        fail(f"tools/list lacks {sorted(missing)}")
    print(f"tools/list: {len(names)} tools")

    found = call(mcp_url, "search_food", query="Tofu")
    refs = [m["ref"] for m in found["matches"]]
    if not refs or not refs[0].startswith("bls:"):
        fail(f"search_food 'Tofu' should start with a bls: ref, got {refs}")
    print("search_food:", refs[0])

    logged = call(mcp_url, "log_food", food_ref=refs[0], grams=100)
    if not logged.get("logged"):
        fail(f"log_food did not log: {logged}")

    protein = call(mcp_url, "day_summary")["totals"]["protein_g"]
    if not protein or protein <= 0:
        fail(f"day_summary protein should be above 0, got {protein}")
    print("day_summary: protein", protein)

    if web_present(web_url):
        status, _ = http(f"{web_url}/")
        if status != 200:
            fail(f"GET {web_url}/ answered {status}")
        print("web: GET / 200")
    else:
        print("web: nothing listens on the web port, skipped (MCP-only entry point)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        fail("usage: smoke_test.py MCP_URL WEB_URL")
    main(sys.argv[1].rstrip("/"), sys.argv[2].rstrip("/"))
