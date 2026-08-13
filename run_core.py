"""Run the Core API only on loopback or Tailscale."""

import os

import uvicorn

from core_server import bind_host_from_env


if __name__ == "__main__":
    uvicorn.run("main:app", host=bind_host_from_env(), port=int(os.environ.get("PORT", "10000")))
