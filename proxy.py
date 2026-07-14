#!/usr/bin/env python3

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import warnings
from urllib.parse import urlsplit

# Suppress noisy urllib3/OpenSSL environment warnings before importing requests.
warnings.filterwarnings(
    "ignore",
    message="urllib3 v2 only supports OpenSSL.*",
)

import requests

# Suppress SSL warnings (since we intentionally disable SSL verification for some tests)
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

OUTPUT_FILE = "workProxy.txt"
SLOW_PROXY_FILE = "slowProxy.txt"
FAILED_PROXY_FILE = "failedProxy.txt"

# Test URLs with different protocols for better compatibility
TEST_URLS = [
    ("http://httpbin.org/ip", True),  # (url, verify_ssl)
    ("https://httpbin.org/ip", False),  # SSL disabled for problematic proxies
    ("http://api.ipify.org?format=json", True),
    ("https://api.ipify.org?format=json", False),
    ("https://ip.me/", False), # Real website test - SSL disabled (many proxies fail this)
    ("https://api.digikala.com/fresh/v1/product/2963408/", False),  # Real website test - SSL disabled
]

# Performance settings
DEFAULT_MAX_WORKERS = 10
FAST_TIMEOUT = 3  # seconds - for fast proxies
SLOW_THRESHOLD = 5  # seconds - proxies taking longer are marked as slow
VERY_SLOW_THRESHOLD = 8  # seconds - proxies taking this long are marked as very slow
PROXY_CONNECT_TIMEOUT = 1.0  # seconds - fail fast on dead/slow connections
PROXY_READ_TIMEOUT = 2.0  # seconds - keep the per-request wait short
PROXY_REQUEST_TIMEOUT = (PROXY_CONNECT_TIMEOUT, PROXY_READ_TIMEOUT)

# ⚙️ Filter Setting: Only save proxies faster than this
MAX_ACCEPTABLE_TIME = 3  # seconds - Only save proxies faster than this threshold
# Settings options:
# MAX_ACCEPTABLE_TIME = 3   → Only [OK-FAST] proxies
# MAX_ACCEPTABLE_TIME = 5   → [OK-FAST] and [OK-NORMAL]
# MAX_ACCEPTABLE_TIME = 8   → [OK-FAST], [OK-NORMAL], [OK-SLOW]
# MAX_ACCEPTABLE_TIME = 100 → All working proxies

# Lock for thread-safe printing
print_lock = threading.Lock()

COMMON_SOCKS_PORTS = {
    1080, 1081, 1085, 1090, 1091, 1092, 1093, 1094, 1095, 1096,
    4145, 4444, 9050, 9150,
}

def select_file_type():
    """Let user choose between JSON and text file"""
    print("\n" + "="*50)
    print("Choose input file type:")
    print("="*50)
    print("[1] JSON file (proxies.json)")
    print("[2] Text file (proxies.txt)")
    print("[3] Custom file path")
    print("="*50)

    while True:
        choice = input("Enter your choice (1-3): ").strip()

        # Handle choice 1
        if choice in ["1", "one"]:
            if os.path.exists("proxies.json"):
                return "proxies.json"
            else:
                print("[ERROR] proxies.json not found in current directory")
                print("Create proxies.json first")
                return None

        # Handle choice 2
        elif choice in ["2", "two"]:
            if os.path.exists("proxies.txt"):
                return "proxies.txt"
            else:
                print("[ERROR] proxies.txt not found in current directory")
                print("Create proxies.txt first")
                return None

        # Handle choice 3
        elif choice in ["3", "three"]:
            file_path = input("Enter file path: ").strip()
            if os.path.exists(file_path):
                return file_path
            else:
                print(f"[ERROR] File '{file_path}' not found")
                return None

        # Invalid choice
        else:
            print(f"[ERROR] Invalid choice '{choice}'. Enter 1, 2, or 3")

def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Fast parallel proxy checker")
    parser.add_argument(
        "input_file",
        nargs="?",
        help="Proxy file path (JSON or text). If omitted, an interactive menu is shown.",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help=f"Number of parallel worker threads (default: {DEFAULT_MAX_WORKERS})",
    )
    return parser.parse_args()

def load_proxies_from_file(file_path):
    """Load proxies from JSON or text file"""
    if not os.path.exists(file_path):
        print(f"[ERROR] File '{file_path}' not found")
        return []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()

        # Try to load as JSON
        if file_path.endswith(".json"):
            data = json.loads(content)
            if isinstance(data, list):
                return [str(p).strip() for p in data if p]
            elif isinstance(data, dict) and "proxies" in data:
                return [str(p).strip() for p in data["proxies"] if p]
            else:
                print("[ERROR] Invalid JSON format. Expected: ['proxy1', 'proxy2'] or {'proxies': ['proxy1', ...]}")
                return []
        else:
            # Text file
            return [line.strip() for line in content.split("\n") if line.strip()]

    except json.JSONDecodeError as e:
        print(f"[ERROR] Failed to read JSON: {e}")
        return []
    except Exception as e:
        print(f"[ERROR] {e}")
        return []

def split_proxy_target(proxy):
    """Split a proxy string into scheme and host:port target."""
    proxy = proxy.strip()
    if "://" in proxy:
        parsed = urlsplit(proxy)
        if not parsed.scheme or not parsed.netloc:
            return None, None
        return parsed.scheme.lower(), parsed.netloc
    return None, proxy

def guess_proxy_candidates(proxy):
    """Return proxy URLs to try, ordered by the best guess first."""
    scheme, target = split_proxy_target(proxy)
    if not target:
        return []

    if scheme:
        return [f"{scheme}://{target}"]

    host, sep, port_text = target.rpartition(":")
    if not sep or not host or not port_text.isdigit():
        return [f"http://{target}"]

    port = int(port_text)
    if port in COMMON_SOCKS_PORTS:
        return [
            f"socks5://{target}",
            f"socks4://{target}",
            f"http://{target}",
        ]

    return [
        f"http://{target}",
        f"socks5://{target}",
        f"socks4://{target}",
    ]

def check_proxy(proxy):
     """Check if proxy is working, return (is_working, response_time, error_type, resolved_proxy)."""
     candidates = guess_proxy_candidates(proxy)
     if not candidates:
         return (False, None, "INVALID", None)

     last_error_type = "FAILED"
     last_fastest_time = None
     last_schema_error = None

     for proxy_url in candidates:
         proxies = {
             "http": proxy_url,
             "https": proxy_url,
         }

         fastest_time = None
         ssl_errors = []
         https_working = False
         ip_me_working = False
         candidate_schema_error = None

         for test_url, verify_ssl in TEST_URLS:
             try:
                 start_time = time.time()

                 response = requests.get(
                     test_url,
                     proxies=proxies,
                     timeout=PROXY_REQUEST_TIMEOUT,
                     allow_redirects=False,
                     verify=verify_ssl  # Key change: handle SSL verification
                 )

                 elapsed_time = time.time() - start_time

                 if response.status_code in [200, 301, 302]:
                     # Track if HTTPS works
                     if test_url.startswith("https://"):
                         https_working = True

                     # Track if ip.me works
                     if "ip.me" in test_url:
                         ip_me_working = True

                     if fastest_time is None or elapsed_time < fastest_time:
                         fastest_time = elapsed_time

             except requests.exceptions.SSLError as e:
                 ssl_errors.append(str(e))
                 continue

             except requests.exceptions.InvalidSchema as e:
                 error_text = str(e).lower()
                 if "socks" in error_text:
                     candidate_schema_error = "SOCKS_MISSING"
                 else:
                     candidate_schema_error = "INVALID"
                 break

             except requests.exceptions.Timeout:
                 continue

             except (requests.exceptions.ProxyError,
                     requests.exceptions.ConnectionError):
                 continue

             except requests.exceptions.RequestException:
                 continue

             except Exception:
                 continue

         if candidate_schema_error:
             last_schema_error = candidate_schema_error
             continue

         # Check if proxy meets requirements: must work with HTTPS AND ip.me
         if https_working and ip_me_working and fastest_time is not None:
             return (True, fastest_time, "OK", proxy_url)

         if not https_working:
             last_error_type = "NO_HTTPS"
         elif not ip_me_working:
             last_error_type = "NO_IP_ME"
         elif ssl_errors and not fastest_time:
             last_error_type = "SSL_ERROR"
         else:
             last_error_type = "FAILED"

         if fastest_time is not None:
             last_fastest_time = fastest_time

     if last_schema_error:
         last_error_type = last_schema_error

     return (False, last_fastest_time, last_error_type, None)

def safe_print(message):
    """Thread-safe printing"""
    with print_lock:
        print(message)

def save_proxy_immediately(proxy):
    """Save good proxy to file immediately"""
    with print_lock:
        try:
            with open(OUTPUT_FILE, "a", encoding="utf-8") as out:
                out.write(proxy + "\n")
        except Exception as e:
            pass

def test_proxy_worker(proxy, index, total):
     """Worker function for thread pool"""
     is_working, response_time, error_type, resolved_proxy = check_proxy(proxy)
     display_proxy = resolved_proxy or proxy

     if is_working:
         if response_time < FAST_TIMEOUT:
             status = "[OK-FAST]"
         elif response_time < SLOW_THRESHOLD:
             status = "[OK-NORMAL]"
         elif response_time < VERY_SLOW_THRESHOLD:
             status = "[OK-SLOW]"
         else:
             status = "[OK-VERY_SLOW]"
         time_str = f" ({response_time:.2f}s)" if response_time else ""
         safe_print(f"[{index}/{total}] {status} {display_proxy}{time_str}")

         # Save proxy immediately if it meets speed requirement
         if response_time <= MAX_ACCEPTABLE_TIME:
             save_proxy_immediately(display_proxy)
     else:
         if error_type == "SSL_ERROR":
             status = "[FAILED-SSL]"
         elif error_type == "NO_HTTPS":
             status = "[FAILED-NO_HTTPS]"
         elif error_type == "NO_IP_ME":
             status = "[FAILED-NO_IP_ME]"
         elif error_type == "SOCKS_MISSING":
             status = "[FAILED-SOCKS_DEP]"
         elif error_type == "INVALID":
             status = "[FAILED-INVALID]"
         else:
             status = "[FAILED]"
         safe_print(f"[{index}/{total}] {status} {display_proxy}")

     return (display_proxy, is_working, response_time, error_type)

def main():
    args = parse_args()
    worker_count = max(1, args.workers)

    # Get file path from argument or let user choose
    if args.input_file:
        input_file = args.input_file
    else:
        input_file = select_file_type()
        if not input_file:
            print("[ERROR] No file selected. Exiting...")
            return

    # Clear output file at start
    try:
        open(OUTPUT_FILE, "w", encoding="utf-8").close()
    except Exception:
        pass

    print(f"\n[INFO] Reading file: {input_file}")
    proxy_list = load_proxies_from_file(input_file)

    if not proxy_list:
        print("[ERROR] No proxies found!")
        return

    print(f"[INFO] Total proxies: {len(proxy_list)}")
    print(f"[INFO] Using up to {worker_count} worker threads")
    print(f"[INFO] Saving good proxies to '{OUTPUT_FILE}' instantly...\n")

    worker_list = proxy_list
    working_proxies = []
    slow_proxies = []
    failed_proxies = []

    # Use ThreadPoolExecutor for parallel testing
    max_workers = min(worker_count, len(worker_list))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(test_proxy_worker, proxy, i+1, len(worker_list)): proxy
            for i, proxy in enumerate(worker_list)
        }

        for future in as_completed(futures):
            proxy, is_working, response_time, error_type = future.result()

            if is_working:
                working_proxies.append((proxy, response_time))
                if response_time >= SLOW_THRESHOLD:
                    slow_proxies.append((proxy, response_time))
            else:
                failed_proxies.append((proxy, error_type))

    # Show summary
    print("\n" + "="*60)

    if working_proxies:
        # Categorize proxies by speed
        fast_proxies = [(p, t) for p, t in working_proxies if t < FAST_TIMEOUT]
        normal_proxies = [(p, t) for p, t in working_proxies if FAST_TIMEOUT <= t < SLOW_THRESHOLD]
        slow_proxies_list = [(p, t) for p, t in working_proxies if t >= SLOW_THRESHOLD]

        # Filter: Only count proxies faster than MAX_ACCEPTABLE_TIME
        filtered_proxies = [(p, t) for p, t in working_proxies if t <= MAX_ACCEPTABLE_TIME]

        print(f"✅ [SUCCESS] Good proxies saved to '{OUTPUT_FILE}' instantly!")
        print(f"   - Saved proxies (≤ {MAX_ACCEPTABLE_TIME}s): {len(filtered_proxies)}")
        print(f"\n📊 All proxies breakdown:")
        print(f"   - Fast proxies (< {FAST_TIMEOUT}s): {len(fast_proxies)}")
        print(f"   - Normal proxies ({FAST_TIMEOUT}s - {SLOW_THRESHOLD}s): {len(normal_proxies)}")
        print(f"   - Slow proxies (≥ {SLOW_THRESHOLD}s): {len(slow_proxies_list)}")
        print(f"   - Total working: {len(working_proxies)}/{len(proxy_list)}")
    else:
        print(f"⚠️  [WARNING] No working proxies found!")
        print(f"   Failed: {len(failed_proxies)}")
        print(f"   SSL Errors: {len([p for p, e in failed_proxies if e == 'SSL_ERROR'])}")

    # Show failure breakdown
    ssl_failed = [(p, e) for p, e in failed_proxies if e == "SSL_ERROR"]
    no_https = [(p, e) for p, e in failed_proxies if e == "NO_HTTPS"]
    no_ip_me = [(p, e) for p, e in failed_proxies if e == "NO_IP_ME"]
    socks_missing = [(p, e) for p, e in failed_proxies if e == "SOCKS_MISSING"]
    other_failed = [(p, e) for p, e in failed_proxies if e not in ["SSL_ERROR", "NO_HTTPS", "NO_IP_ME", "SOCKS_MISSING", "INVALID"]]

    if failed_proxies:
        print(f"\n📊 Failed proxies breakdown:")
        print(f"   - No HTTPS support: {len(no_https)}")
        print(f"   - Can't access ip.me: {len(no_ip_me)}")
        if socks_missing:
            print(f"   - SOCKS dependency missing: {len(socks_missing)}")
        if ssl_failed:
            print(f"   - SSL certificate errors: {len(ssl_failed)}")
        if other_failed:
            print(f"   - Other failures: {len(other_failed)}")

    if no_https:
        print(f"\n⚠️  [{len(no_https)}] Proxies without HTTPS support (ignored):")
        for proxy, _ in no_https[:5]:  # Show first 5
            print(f"   - {proxy}")
        if len(no_https) > 5:
            print(f"   ... and {len(no_https) - 5} more")

    if no_ip_me:
        print(f"\n⚠️  [{len(no_ip_me)}] Proxies that can't access ip.me (ignored):")
        for proxy, _ in no_ip_me[:5]:  # Show first 5
            print(f"   - {proxy}")
        if len(no_ip_me) > 5:
            print(f"   ... and {len(no_ip_me) - 5} more")

    if socks_missing:
        print(f"\n⚠️  [{len(socks_missing)}] SOCKS proxies could not be tested because PySocks is missing:")
        print("   Install dependencies with: pip3 install -r requirements.txt")
        for proxy, _ in socks_missing[:5]:
            print(f"   - {proxy}")
        if len(socks_missing) > 5:
            print(f"   ... and {len(socks_missing) - 5} more")

    if ssl_failed:
        print(f"\n⚠️  [{len(ssl_failed)}] Proxies with SSL certificate errors:")
        print("   These might work with: curl, Firefox, or chrome --no-default-browser-check")
        for proxy, _ in ssl_failed[:5]:  # Show first 5
            print(f"   - {proxy}")
        if len(ssl_failed) > 5:
            print(f"   ... and {len(ssl_failed) - 5} more")

    print("="*60 + "\n")

if __name__ == "__main__":
    main()
