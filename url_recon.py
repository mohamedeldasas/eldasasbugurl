#!/usr/bin/env python3
"""
url_recon.py - جمع الـ URLs وفلترتها لاختبار open redirect
استخدمه بس على targets جوه الـ scope بتاع برنامج مسموح.

الاستخدام:
    python3 url_recon.py target.com
    python3 url_recon.py target.com -o out_dir --threads 50 --depth 3
"""

import argparse
import math
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse, parse_qsl

BANNER_TEXT = "ELDASASBUG"


def print_banner():
    RED = "\033[91m"
    BLACK_BG = "\033[40m"
    RESET = "\033[0m"
    art = None
    if shutil.which("figlet"):
        try:
            r = subprocess.run(["figlet", BANNER_TEXT], capture_output=True,
                               text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                art = r.stdout.rstrip("\n")
        except Exception:
            pass
    if not art:
        pad = f"   {BANNER_TEXT}   "
        border = "#" * len(pad)
        art = f"{border}\n{pad}\n{border}"
    print(f"{BLACK_BG}{RED}{art}{RESET}\n")

URL_RE = re.compile(r"https?://[^\s\]\[\"'<>]+")

# أسماء parameters المشهورة في ثغرات open redirect
REDIRECT_PARAMS = {
    "url", "uri", "u", "next", "redirect", "redirect_url", "redirect_uri",
    "redirecturl", "redirecturi", "return", "return_url", "returnurl",
    "returnto", "return_to", "continue", "dest", "destination", "go", "goto",
    "target", "rurl", "r", "out", "view", "link", "forward", "forward_url",
    "callback", "callback_url", "back", "backurl", "back_url", "to",
    "image_url", "checkout_url", "success_url", "fail_url", "login_url",
    "logout", "ref", "referrer", "site", "domain", "host", "path", "page",
    "navigation", "open", "jump", "jump_url", "service", "origin",
}


def log(msg):
    print(f"[*] {msg}", flush=True)


# ---------------- التنزيل التلقائي للأدوات ----------------

GO_PKGS = {
    "gau": "github.com/lc/gau/v2/cmd/gau@latest",
    "waybackurls": "github.com/tomnomnom/waybackurls@latest",
    "katana": "github.com/projectdiscovery/katana/cmd/katana@latest",
    "hakrawler": "github.com/hakluke/hakrawler@latest",
    "gospider": "github.com/jaeles-project/gospider@latest",
    "httpx": "github.com/projectdiscovery/httpx/cmd/httpx@latest",
}

PIP_PKGS = {
    "waymore": "waymore",
    "paramspider": "git+https://github.com/devanshbatham/ParamSpider",
}


def setup_path():
    """بيضيف مسارات Go و pip للـ PATH (وبيحطها الأول عشان httpx بتاع Go ياخد الأولوية)."""
    extra = [os.path.expanduser("~/go/bin"), os.path.expanduser("~/.local/bin")]
    gopath = os.environ.get("GOPATH")
    if gopath:
        extra.insert(0, os.path.join(gopath, "bin"))
    os.environ["PATH"] = os.pathsep.join(extra + [os.environ.get("PATH", "")])


def sh(cmd, timeout=900):
    """بيشغل أمر ويرجع (نجح؟, الـ output كله)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, errors="ignore")
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return False, str(e)


def have(name):
    """بيتأكد إن الأداة موجودة. وبالنسبة لـ httpx بيتأكد إنها بتاعة ProjectDiscovery."""
    if not shutil.which(name):
        return False
    if name == "httpx":
        _, out = sh([name, "-version"], timeout=30)
        return "projectdiscovery" in out.lower() or "current version" in out.lower()
    return True


def install_go_tool(name):
    if not shutil.which("go"):
        log("Go مش موجود، بحاول أنزله...")
        if os.geteuid() == 0:
            sh(["apt-get", "install", "-y", "golang-go"])
        elif shutil.which("sudo"):
            sh(["sudo", "-n", "apt-get", "install", "-y", "golang-go"])
        if not shutil.which("go"):
            log("  معرفتش أنزل Go (نزله بإيدك: sudo apt install golang-go)")
            return False
    ok, out = sh(["go", "install", "-v", GO_PKGS[name]])
    if not ok:
        log(f"  go install فشل: {out.strip()[-200:]}")
    return ok


def install_pip_tool(name):
    pkg = PIP_PKGS[name]
    if shutil.which("pipx"):
        ok, _ = sh(["pipx", "install", pkg])
        if ok:
            return True
    ok, out = sh([sys.executable, "-m", "pip", "install", "--user",
                  "--break-system-packages", pkg])
    if not ok:
        ok, out = sh([sys.executable, "-m", "pip", "install", "--user", pkg])
    if not ok:
        log(f"  pip فشل: {out.strip()[-200:]}")
    return ok


def ensure_tool(name, auto_install=True):
    """لو الأداة موجودة يرجع True. لو لأ يحاول ينزلها. لو معرفش يرجع False (وتتعدى)."""
    if have(name):
        return True
    if not auto_install:
        return False
    log(f"{name} مش موجودة، بحاول أنزلها...")
    if name in GO_PKGS:
        install_go_tool(name)
    elif name in PIP_PKGS:
        install_pip_tool(name)
    setup_path()
    if have(name):
        log(f"  {name} اتنزلت بنجاح")
        return True
    log(f"  معرفتش أنزل {name}")
    return False


def run(cmd, timeout=1800, stdin_data=None):
    """بيشغل أمر ويرجع الـ stdout. لو فشل بيرجع نص فاضي."""
    try:
        res = subprocess.run(
            cmd,
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="ignore",
        )
        return res.stdout
    except subprocess.TimeoutExpired:
        log(f"timeout: {cmd[0]}")
    except Exception as e:
        log(f"error في {cmd[0]}: {e}")
    return ""


def extract_urls(text):
    return set(URL_RE.findall(text))


def in_scope(url, domain):
    host = (urlparse(url).hostname or "").lower()
    return host == domain or host.endswith("." + domain)


# ---------------- أدوات الجمع ----------------

def tool_gau(domain, a):
    return extract_urls(run(["gau", "--subs", "--threads", str(a.threads), domain]))


def tool_waybackurls(domain, a):
    return extract_urls(run(["waybackurls"], stdin_data=domain + "\n"))


def tool_waymore(domain, a):
    out = os.path.join(a.tmp, "waymore.txt")
    run(["waymore", "-i", domain, "-mode", "U", "-oU", out])
    urls = set()
    if os.path.exists(out):
        with open(out, errors="ignore") as f:
            urls = extract_urls(f.read())
        os.remove(out)
    return urls


def tool_katana(domain, a):
    c = max(1, min(int(a.rps), a.threads))
    cmd = ["katana", "-u", f"https://{domain}", "-d", str(a.depth),
           "-jc", "-silent", "-rl", str(a.rps), "-c", str(c)]
    return extract_urls(run(cmd))


def tool_hakrawler(domain, a):
    return extract_urls(run(
        ["hakrawler", "-d", str(a.depth), "-subs"],
        stdin_data=f"https://{domain}\n",
    ))


def tool_gospider(domain, a):
    # gospider مفيهاش rate limit حقيقي، فبنضمن الحد بـ concurrency=1 + تأخير
    # بين كل طلب (بنقرّب لأعلى عشان نضمن إننا متعديناش الرقم).
    delay = max(1, math.ceil(1 / a.rps))
    return extract_urls(run([
        "gospider", "-s", f"https://{domain}", "-d", str(a.depth),
        "-c", "1", "-t", "1", "--delay", str(delay), "--other-source", "-q",
    ]))


def tool_paramspider(domain, a):
    run(["paramspider", "-d", domain])
    urls = set()
    res_file = os.path.join("results", f"{domain}.txt")
    if os.path.exists(res_file):
        with open(res_file, errors="ignore") as f:
            urls = extract_urls(f.read())
        os.remove(res_file)
        try:
            os.rmdir("results")
        except OSError:
            pass
    return urls


TOOLS = {
    "gau": tool_gau,
    "waybackurls": tool_waybackurls,
    "waymore": tool_waymore,
    "katana": tool_katana,
    "hakrawler": tool_hakrawler,
    "gospider": tool_gospider,
    "paramspider": tool_paramspider,
}

# أدوات مفيهاش أي ضمان للسرعة (مش بتدعم rate limit حقيقي)، فبنتخطاها
# دايماً عشان نضمن إننا ملتزمين بالرقم اللي المستخدم حدده.
NO_RATE_LIMIT_TOOLS = {"hakrawler"}


# ---------------- المراحل ----------------

def stage_collect(domain, a):
    all_urls = set()
    for name, fn in TOOLS.items():
        if name in NO_RATE_LIMIT_TOOLS:
            log(f"هعدي على {name}: مفيهاش rate limit مضمون، وأنت حددت حد "
                f"{a.rps} طلب/ثانية ومينفعش نضمنه معاها")
            continue
        if not ensure_tool(name, a.auto_install):
            log(f"هعدي على {name}")
            continue
        log(f"شغال: {name}")
        found = fn(domain, a)
        found = {u for u in found if in_scope(u, domain)}
        log(f"  {name}: {len(found)} URL")
        all_urls |= found

    raw_file = os.path.join(a.out, "all_urls.txt")
    with open(raw_file, "w") as f:
        f.write("\n".join(sorted(all_urls)) + "\n")
    log(f"المجموع بعد إزالة التكرار: {len(all_urls)} -> {raw_file}")
    return raw_file, len(all_urls)


def stage_probe(raw_file, a):
    if not ensure_tool("httpx", a.auto_install):
        sys.exit("[!] httpx (بتاع ProjectDiscovery) مش موجود ومعرفتش أنزله. "
                 "نزله بإيدك: go install github.com/projectdiscovery/httpx/cmd/httpx@latest")
    live_file = os.path.join(a.out, "live_urls.txt")
    log(f"بفحص مين الـ URLs الشغالة (بحد {a.rps} طلب/ثانية)...")
    t = max(1, min(int(a.rps), a.threads))
    subprocess.run([
        "httpx", "-l", raw_file, "-silent", "-rl", str(a.rps), "-t", str(t),
        "-mc", "200,201,204,301,302,303,307,308,401,403",
        "-o", live_file,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if not os.path.exists(live_file):
        open(live_file, "w").close()

    os.remove(raw_file)  # مسح الملف القديم
    log(f"اتمسح {os.path.basename(raw_file)}")
    return live_file


def stage_split(live_file, a):
    js_file = os.path.join(a.out, "js_urls.txt")
    redirect_file = os.path.join(a.out, "redirect_params.txt")

    with open(live_file, errors="ignore") as f:
        urls = [l.strip() for l in f if l.strip()]

    js_urls, redirect_urls = set(), set()
    for u in urls:
        p = urlparse(u)
        if p.path.lower().endswith((".js", ".mjs")):
            js_urls.add(u)
        params = {k.lower() for k, _ in parse_qsl(p.query, keep_blank_values=True)}
        if params & REDIRECT_PARAMS:
            redirect_urls.add(u)

    with open(js_file, "w") as f:
        f.write("\n".join(sorted(js_urls)) + ("\n" if js_urls else ""))
    with open(redirect_file, "w") as f:
        f.write("\n".join(sorted(redirect_urls)) + ("\n" if redirect_urls else ""))

    log(f"JS: {len(js_urls)} -> {js_file}")
    log(f"Redirect params: {len(redirect_urls)} -> {redirect_file}")


def ask_rps():
    while True:
        raw = input("كام طلب في الثانية تحب السكريبت يلتزم بيه على التارجت ده؟ (مثلاً 5): ").strip()
        try:
            rps = float(raw)
        except ValueError:
            print("اكتب رقم (ممكن يكون عشري زي 0.5)."); continue
        if rps <= 0:
            print("لازم يكون أكبر من صفر."); continue
        return rps


def main():
    print_banner()
    ap = argparse.ArgumentParser(description="URL recon + filtering")
    ap.add_argument("domain", help="الدومين (مثلاً target.com) من غير https://")
    ap.add_argument("-o", "--out", default="recon_out", help="فولدر النتايج")
    ap.add_argument("--threads", type=int, default=30)
    ap.add_argument("--depth", type=int, default=3, help="عمق الـ crawling")
    ap.add_argument("--rps", type=float, default=None,
                    help="أقصى عدد طلبات في الثانية على التارجت (لو مديتهوش هيسألك)")
    ap.add_argument("--no-install", dest="auto_install", action="store_false",
                    help="متنزّلش الأدوات الناقصة تلقائياً")
    a = ap.parse_args()
    setup_path()

    if a.rps is None:
        a.rps = ask_rps()
    log(f"هلتزم بحد أقصى {a.rps} طلب/ثانية على كل أداة بتكلم التارجت")

    domain = a.domain.lower().replace("https://", "").replace("http://", "").strip("/")
    a.out = os.path.abspath(a.out)
    a.tmp = os.path.join(a.out, ".tmp")
    os.makedirs(a.tmp, exist_ok=True)

    raw_file, count = stage_collect(domain, a)
    if count == 0:
        sys.exit("[!] مفيش URLs اتجمعت. اتأكد إن الأدوات منزلة.")

    live_file = stage_probe(raw_file, a)
    stage_split(live_file, a)
    shutil.rmtree(a.tmp, ignore_errors=True)
    log(f"خلصنا. النتايج في: {a.out}")


if __name__ == "__main__":
    main()
