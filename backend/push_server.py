"""MCP server that sends a push notification through Pushover."""

import os
import sys
import requests
from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP
from . import config  # noqa: F401  (loads the environment)

pushover_user = os.getenv("PUSHOVER_USER")
pushover_token = os.getenv("PUSHOVER_TOKEN")
pushover_url = "https://api.pushover.net/1/messages.json"

mcp = FastMCP("push_server")


class PushModelArgs(BaseModel):
    message: str = Field(description="A brief message to push")


@mcp.tool()
def push(args: PushModelArgs):
    """Send a push notification with this brief message"""
    print(f"Push: {args.message}", file=sys.stderr)  # stdout carries the MCP protocol
    if not (pushover_user and pushover_token):
        return "Push notifications are not configured; message noted"
    try:
        requests.post(pushover_url, data={"user": pushover_user, "token": pushover_token, "message": args.message}, timeout=15)
    except requests.RequestException as e:
        return f"Push notification failed: {e}"
    return "Push notification sent"


if __name__ == "__main__":
    mcp.run(transport="stdio")
