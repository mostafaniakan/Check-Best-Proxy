# Check Proxy - Proxy Checker

A fast, parallel proxy checking program that verifies if proxies are working properly

## Features
✅ **Parallel testing** - Tests proxies simultaneously with configurable worker count
✅ **HTTP, SOCKS4, SOCKS5 support** - Works with explicit schemes or auto-detected `ip:port` entries
✅ **SSL Certificate Handling** - Disables SSL verification for problematic proxies
✅ **HTTP Fallback** - Tests with both HTTP and HTTPS URLs
✅ **Speed Detection** - Identifies fast, normal, and slow proxies
✅ **Better Error Handling** - Distinguishes between SSL errors and connection failures
✅ Interactive menu to choose between JSON and text files
✅ Tests proxies against fast, reliable URLs
✅ Saves working proxies to `workProxy.txt`
✅ English output messages
✅ Shows progress as [current/total]
✅ Thread-safe output
✅ Shows response time for each proxy

## Installation

### Requirements
```bash
pip3 install -r requirements.txt
```

## Usage

### Method 1: Interactive Menu (Recommended)
Just run the script and choose which file type to use:
```bash
python3 proxy.py
```

You'll see a menu:
```
==================================================
Choose input file type:
==================================================
[1] JSON file (proxies.json)
[2] Text file (proxies.txt)
[3] Custom file path
==================================================
Enter your choice (1-3):
```

### Method 2: Direct File Path
Pass the file path as an argument:
```bash
python3 proxy.py proxies.txt
python3 proxy.py proxies.json
python3 proxy.py /path/to/your/proxies.json
```

You can also choose the number of worker threads:
```bash
python3 proxy.py proxies.txt --workers 20
python3 proxy.py proxies.json -w 32
```

Supported input styles:
```text
70.166.65.160:4145
http://144.124.227.88:3129
socks4://138.124.106.230:443
socks5://194.59.186.35:1080
```

If a proxy is given as plain `ip:port`, the checker guesses the protocol order and stores the working normalized proxy URL in `workProxy.txt`.

### Method 3: Direct Execution
```bash
./proxy.py
```

## File Formats

### Text File (proxies.txt)
One proxy per line:
```
192.168.1.1:8080
10.0.0.1:3128
127.0.0.1:8888
proxy.example.com:3128
```

### JSON File (proxies.json)
Option 1 - Simple array:
```json
[
  "192.168.1.1:8080",
  "10.0.0.1:3128",
  "127.0.0.1:8888"
]
```

Option 2 - Object with proxies key:
```json
{
  "proxies": [
    "192.168.1.1:8080",
    "10.0.0.1:3128",
    "127.0.0.1:8888"
  ]
}
```

## Output

Working proxies are saved to `workProxy.txt`:
```
192.168.1.1:8080
10.0.0.1:3128
```

Console output shows:
```
[1/3] [OK] 192.168.1.1:8080
[2/3] [FAILED] 10.0.0.1:3128
[3/3] [OK] 127.0.0.1:8888
```

## Performance

### What Makes It Fast?
1. **Parallel Testing** - Tests multiple proxies at once with a configurable worker pool
2. **Optimized URLs** - Uses fast, lightweight test endpoints
3. **Short Timeouts** - 5 second timeout per test (vs 10+ seconds for others)
4. **Efficient HTTP** - No redirect following to save time
5. **Protocol Auto-Detection** - Plain `ip:port` entries are probed as HTTP or SOCKS depending on the port and working result

### Speed Comparison
- **Old way** (sequential): 100 proxies × 5 seconds = ~500+ seconds
- **New way** (parallel with workers): 100 proxies ÷ 10 × 5 seconds = ~50 seconds ⚡

## Settings

| Setting | Value | Reason |
|---------|-------|--------|
| Max Workers | 10 by default | Balance between speed and system load; override with `--workers` |
| Fast Timeout | 3 seconds | Identify fast proxies |
| Slow Threshold | 5 seconds | Proxies slower than this are marked as slow |
| Very Slow Threshold | 8 seconds | Proxies slower than this are marked as very slow |
| Proxy Request Timeout | 1s connect / 2s read | Fail faster on dead or slow proxies |
| SSL Verification | Disabled for some tests | Handle proxies with certificate issues |

## Output Indicators

- `[OK-FAST]` - Proxy works in < 3 seconds
- `[OK-NORMAL]` - Proxy works in 3-5 seconds  
- `[OK-SLOW]` - Proxy works in 5-8 seconds
- `[OK-VERY_SLOW]` - Proxy works but is very slow (> 8 seconds)
- `[FAILED]` - Proxy doesn't work
- `[FAILED-SSL]` - Proxy has SSL certificate issues (may still work with curl/Firefox)

## Proxy Issues Resolved

### 1. SSL Certificate Errors
**Problem:** Some proxies give `net::ERR_CERT_AUTHORITY_INVALID` errors

**Solution:** 
- The checker now tests with SSL verification disabled as a fallback
- If a proxy has SSL issues, it's marked as `[FAILED-SSL]`
- These proxies may still work with tools that ignore SSL warnings (curl, Firefox, etc.)

### 2. Slow Proxies
**Problem:** Some proxies are too slow and timeout

**Solution:**
- Response times are now measured and displayed
- Proxies are categorized by speed
- You can filter results by speed if needed
- Timeout is adaptive based on protocol being tested

## How It Works

1. Choose or specify a proxy file (JSON or text)
2. Program reads all proxies from the file
3. Tests proxies in parallel against fast URLs with both HTTP and HTTPS using the configured worker count:
   - http://httpbin.org/ip (with SSL verification)
   - https://httpbin.org/ip (SSL verification disabled)
   - http://api.ipify.org?format=json (with SSL verification)
   - https://api.ipify.org?format=json (SSL verification disabled)
4. If proxy works with ANY of these URLs, it's marked as working
5. Response time is recorded for speed analysis
6. Working proxies are saved to `workProxy.txt`
7. Non-working proxies are ignored (but SSL errors are reported separately)
8. Tests continue until all proxies are checked
