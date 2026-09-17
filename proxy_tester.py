#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from time import sleep

import requests
from colorama import Fore, Style, init

init(autoreset=True)


def check_proxy(args):
    index, total, proxy = args
    proxy = proxy.strip()
    proxies = {
        "http": f"http://{proxy}",
        "https": f"https://{proxy}",
    }
    try:
        response = requests.get("http://httpbin.org/ip", proxies=proxies, timeout=5)
        if response.status_code == 200:
            result = f"{Fore.GREEN}[{index}/{total}] ✅ {proxy}{Style.RESET_ALL}"
            is_valid = True
        else:
            result = f"{Fore.RED}[{index}/{total}] ❌ {proxy}{Style.RESET_ALL}"
            is_valid = False
    except requests.exceptions.RequestException:
        result = f"{Fore.RED}[{index}/{total}] ❌ {proxy}{Style.RESET_ALL}"
        is_valid = False
    sleep(0.5)
    return (result, proxy if is_valid else None)


if __name__ == "__main__":
    with open("proxies.txt", "r") as file:
        proxies_list = [line.strip() for line in file if line.strip()]
    total_proxies = len(proxies_list)
    valid_proxies = []
    args_list = [
        (idx, total_proxies, proxy) for idx, proxy in enumerate(proxies_list, start=1)
    ]
    with ThreadPoolExecutor(max_workers=5) as executor:
        for result, valid_proxy in executor.map(check_proxy, args_list):
            print(result)
            if valid_proxy:
                valid_proxies.append(valid_proxy)
    if valid_proxies:
        save_choice = input("Do you want to save the valid proxies to a file? (y/n): ")
        if save_choice.lower() == "y":
            output_file = input(
                "Enter the filename to save valid proxies (default: valid_proxies.txt): "
            ).strip()
            if not output_file:
                output_file = "valid_proxies.txt"
            with open(output_file, "w") as f:
                f.writelines(f"{proxy}\n" for proxy in valid_proxies)
            print(f"Valid proxies saved to {output_file}")
    else:
        print("No valid proxies found.")
