"""把一個 HTML 頁面加密成「密碼頁」：沒有密碼只看得到輸入框，原始碼裡只有亂碼。

由 .github/workflows/pages.yml 在發佈前呼叫：
    python .github/seal.py <來源.html> <輸出.html> --store <記住金鑰用的名字>

- 密碼讀環境變數 SITE_PASSWORD（repo Settings → Secrets → Actions）。沒設就失敗，
  寧可不發佈也不要發出未加密的版本。
- 加密方式沿用收藏筆記（saved-notes）：PBKDF2 推導金鑰 → AES-GCM；瀏覽器用 WebCrypto 解。
- 鹽放 .github/site_salt.txt（不是秘密）。鹽要固定：手機「記住」的是金鑰，鹽一換就要重打密碼。
- 只擋「知道網址的路人」：repo 是公開的，原始碼在 GitHub 上照樣看得到。
"""
import argparse
import base64
import html
import json
import os
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITER = 600_000   # 跟收藏筆記一樣：拖慢暴力猜密碼，手機解一次約 0.5～1 秒
SALT_FILE = Path(__file__).with_name("site_salt.txt")

SHELL = r"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<title>__TITLE__</title>
<style>
:root{--bg:#f5f2ec;--card:#fff;--ink:#1f1d1a;--sub:#6d675e;--line:#e4ded3;--accent:#b4532f}
@media (prefers-color-scheme:dark){:root{--bg:#171614;--card:#22201d;--ink:#eeeae3;--sub:#a39d93;--line:#34312c;--accent:#e08159}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px;
  background:var(--bg);color:var(--ink);font:16px/1.6 "PingFang TC","Noto Sans TC","Microsoft JhengHei",system-ui,sans-serif}
form{width:100%;max-width:340px;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:24px 20px}
h1{font-size:20px;margin:0 0 4px}
.lock{width:30px;height:30px;color:var(--accent);fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;margin-bottom:8px}
p{margin:0 0 16px;color:var(--sub);font-size:14px}
input[type=password]{width:100%;padding:11px 12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink);font-size:16px}
label{display:flex;align-items:center;gap:8px;margin:12px 0 16px;font-size:14px;color:var(--sub)}
button{width:100%;padding:11px;border:0;border-radius:10px;background:var(--ink);color:var(--bg);font-size:16px;font-weight:600;cursor:pointer}
button:disabled{opacity:.6}
#err{color:var(--accent);font-size:14px;min-height:1.6em;margin-top:10px}
</style>
</head>
<body>
<form id="f" hidden>
  <svg class="lock" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="10.5" width="16" height="10.5" rx="2.5"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/><circle cx="12" cy="15.5" r="1.4" fill="currentColor" stroke="none"/></svg>
  <h1>__TITLE__</h1>
  <p>私人頁面，請輸入密碼</p>
  <input id="pw" type="password" autocomplete="current-password" autofocus>
  <label><input id="rem" type="checkbox" checked>在這台裝置上記住</label>
  <button id="go">開啟</button>
  <div id="err"></div>
</form>
<script>
// 內容整頁用 AES-GCM 加密；金鑰由密碼經 PBKDF2 推導。原始碼裡只有亂碼，沒有密碼也沒有內容。
// 整段包在函式裡：document.open() 換頁不會清掉全域變數，留在全域會跟內頁的 const 撞名
(() => {
const P = __PAYLOAD__;
const STORE = __STORE__;
const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));

async function keyFrom(pw){
  const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(pw), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey({name:'PBKDF2', salt:b64(P.salt), iterations:P.iter, hash:'SHA-256'},
    base, {name:'AES-GCM', length:256}, true, ['decrypt']);
}
// 密碼錯的話 decrypt 會丟例外（GCM 驗證不過），所以能解開＝密碼對
const decrypt = async key => new TextDecoder().decode(await crypto.subtle.decrypt({name:'AES-GCM', iv:b64(P.iv)}, key, b64(P.ct)));
// 頁面還在載入時就 document.write，內容會被接在後面而不是取代整頁（記住的金鑰解得很快，會踩到）
function show(html){
  const swap = () => {
    document.open(); document.write(html); document.close();
    // 換頁後瀏覽器不會自己捲到網址的 #錨點，補捲一次
    if (location.hash) setTimeout(() => { try { document.querySelector(decodeURIComponent(location.hash))?.scrollIntoView(); } catch (e) {} }, 300);
  };
  document.readyState === 'complete' ? swap() : addEventListener('load', swap, {once:true});
}
function store(v){ try { v ? localStorage.setItem(STORE, v) : localStorage.removeItem(STORE); } catch (e) {} }

(async () => {
  // 記住的金鑰先試；對不上（換過密碼）就清掉、改問密碼
  let saved = null; try { saved = localStorage.getItem(STORE); } catch (e) {}
  if (saved) {
    try { const key = await crypto.subtle.importKey('raw', b64(saved), 'AES-GCM', true, ['decrypt']); return show(await decrypt(key)); }
    catch (e) { store(null); }
  }
  const f = document.getElementById('f'), err = document.getElementById('err'), go = document.getElementById('go');
  f.hidden = false;
  f.addEventListener('submit', async ev => {
    ev.preventDefault(); err.textContent = ''; go.disabled = true; go.textContent = '解密中…';
    try {
      const key = await keyFrom(document.getElementById('pw').value);
      const html = await decrypt(key);   // 解開了才記住，錯的密碼不會被存
      if (document.getElementById('rem').checked) {
        const raw = new Uint8Array(await crypto.subtle.exportKey('raw', key));
        store(btoa(String.fromCharCode(...raw)));
      }
      show(html);
    } catch (e) {
      err.textContent = '密碼不對'; go.disabled = false; go.textContent = '開啟';
    }
  });
})();
})();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--store", required=True, help="localStorage 的鍵名；同網域的每個站要不同")
    a = ap.parse_args()

    password = os.environ.get("SITE_PASSWORD", "")
    if not password:
        sys.exit("SITE_PASSWORD 沒設定（repo Settings → Secrets and variables → Actions）。不發佈未加密的版本。")

    salt = base64.b64decode(SALT_FILE.read_text(encoding="utf-8").strip())
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(password.encode())

    plain = Path(a.src).read_text(encoding="utf-8")
    m = re.search(r"<title>(.*?)</title>", plain, re.S)
    title = html.escape(html.unescape(m.group(1).strip())) if m else "私人頁面"

    iv = os.urandom(12)   # iv 每次都要換；鹽不用
    sealed = AESGCM(key).encrypt(iv, plain.encode("utf-8"), None)   # 密文＋16 bytes tag，跟 WebCrypto 格式相同
    b64 = lambda x: base64.b64encode(x).decode()
    payload = {"salt": b64(salt), "iv": b64(iv), "iter": ITER, "ct": b64(sealed)}

    page = (SHELL.replace("__TITLE__", title)
                 .replace("__STORE__", json.dumps(a.store))
                 .replace("__PAYLOAD__", json.dumps(payload)))
    Path(a.out).write_text(page, encoding="utf-8")
    print(f"加密完成：{a.src} → {a.out}（{len(page.encode()) / 1e3:.0f} KB）")


if __name__ == "__main__":
    main()
