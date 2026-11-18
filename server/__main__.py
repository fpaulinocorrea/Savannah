"""Start Savannah:  python -m server"""

import uvicorn

from . import config
from .netinfo import phone_urls


def main() -> None:
    config.ensure_folders()
    print()
    print("  Savannah is running")
    print(f"  On this computer:  http://localhost:{config.PORT}")
    for url in phone_urls(config.PORT):
        print(f"  On your phone:     {url}   (same Wi-Fi)")
    print("  To stop: close this window or press Ctrl+C")
    print()
    uvicorn.run("server.app:app", host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
