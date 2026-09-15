# -*- coding: utf-8 -*-
"""產生 docs/index.html 裡那段 SVG 圖示 CSS（CSS mask + data URI，吃 currentColor、不連外網）。

用法：改上面的 ICONS → `python tools/mkicons.py` → 把 icons.css 的內容
貼回 docs/index.html <style> 裡「SVG 圖示」那一段（從 :root{ 到 .ic-chev{...} 那行）。
刻意不放 scripts/：那個路徑一 push 就會觸發 update.yml 重算 data.json。
"""

ICONS = {
 "help":  "<circle cx='12' cy='12' r='9'/><path d='M9.4 9.4a2.7 2.7 0 1 1 3.2 3.7c-.5.2-.8.7-.8 1.3v.5'/><path d='M11.8 17.6v.1'/>",
 "info":  "<circle cx='12' cy='12' r='9'/><path d='M12 11.2v5.3'/><path d='M12 7.6v.1'/>",
 "bars":  "<path d='M3.8 20.6h16.4'/><path d='M7.6 20.6V12.4'/><path d='M12 20.6V5.6'/><path d='M16.4 20.6V9.4'/>",
 "line":  "<path d='M3.6 3.8v16.4h16.6'/><path d='M6.8 16.6l4.2-4.8 3 2.6 6.4-7.2'/>",
 "back":  "<path d='M3.6 12a8.4 8.4 0 1 0 8.4-8.4 8.4 8.4 0 0 0-5.9 2.4L3.7 8.4'/><path d='M3.4 4v4.6h4.6'/><path d='M12 8v4.3l3 1.8'/>",
 "trash": "<path d='M4.6 6.6h14.8'/><path d='M9.6 6.6V4.3h4.8v2.3'/><path d='M6.9 6.6l.9 13.1h8.4l.9-13.1'/>",
 "close": "<path d='M6.2 6.2l11.6 11.6M17.8 6.2L6.2 17.8'/>",
 "tag":   "<path d='M11.4 3.4H3.4v8l9.4 9.4 8-8z'/><circle cx='7.4' cy='7.4' r='1.35'/>",
 "pulse": "<path d='M2.8 12.4h4.2l2.4-6.6 4 13.2 2.3-6.6h5.5'/>",
 "print": "<path d='M4.2 12a7.8 7.8 0 0 1 15.6 0'/><path d='M7.4 13.6a4.6 4.6 0 0 1 9.2 0v2.6'/><path d='M10.5 14.3a1.5 1.5 0 0 1 3 0v5'/>",
 "flame": "<path d='M12 21.3c3.6 0 6.4-2.6 6.4-6.1 0-2.8-1.6-4.7-3-6.3-1.1-1.2-2-2.6-2-4.9-2.4 1.6-3.7 3.6-3.7 5.4 0 1.1.4 1.9.4 2.6 0 .8-.6 1.3-1.3 1.3-.9 0-1.6-.7-1.8-2-1 1.3-1.4 2.8-1.4 4.3 0 3.3 2.8 5.7 6.4 5.7z'/>",
 "coins": "<ellipse cx='12' cy='6.2' rx='7.1' ry='3'/><path d='M4.9 6.2v5.4c0 1.7 3.2 3 7.1 3s7.1-1.3 7.1-3V6.2'/><path d='M4.9 11.6v5.4c0 1.7 3.2 3 7.1 3s7.1-1.3 7.1-3v-5.4'/>",
 "eye":   "<path d='M2.4 12S5.9 5.6 12 5.6 21.6 12 21.6 12 18.1 18.4 12 18.4 2.4 12 2.4 12z'/><circle cx='12' cy='12' r='2.9'/>",
 "sale":  "<path d='M6.2 18.4L17.8 5.6'/><circle cx='7.9' cy='7.7' r='2.5'/><circle cx='16.1' cy='16.3' r='2.5'/>",
 "lock":  "<rect x='4.6' y='10.4' width='14.8' height='9.4' rx='2.1'/><path d='M8.1 10.4V7.8a3.9 3.9 0 0 1 7.8 0v2.6'/>",
 "moon":  "<path d='M20.3 14.6A8.9 8.9 0 0 1 9.4 3.7a8.9 8.9 0 1 0 10.9 10.9z'/>",
 "plus":  "<circle cx='12' cy='12' r='9'/><path d='M12 7.8v8.4M7.8 12h8.4'/>",
 "find":  "<circle cx='10.7' cy='10.7' r='6.9'/><path d='M15.7 15.7l5.1 5.1'/>",
 "note":  "<path d='M4.4 5.2h15.2v10.4h-8.9L6 19.4v-3.8H4.4z'/><path d='M8.2 9.2h7.6M8.2 12.2h5'/>",
 "warn":  "<path d='M12 3.9L21.4 20H2.6z'/><path d='M12 9.8v4.5'/><path d='M12 17.2v.1'/>",
 "bolt":  "<path d='M13.3 2.6L4.6 13.9h6.2l-.9 7.6 8.6-11.3h-6.2z'/>",
 "chev":  "<path d='M6.4 9.2L12 14.8l5.6-5.6'/>",
}

def enc(body, sw="1.9"):
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
           "stroke='#000' stroke-width='" + sw + "' stroke-linecap='round' stroke-linejoin='round'>"
           + body + "</svg>")
    return svg.replace("%", "%25").replace("#", "%23").replace("<", "%3C").replace(">", "%3E")

L = []
L.append("  /* SVG 圖示：CSS mask + data URI。吃 currentColor、跟著 font-size 縮放、不連外網。")
L.append("     改圖示請改 scripts/ 外的產生器 mkicons.py，別手改這串編碼。 */")
L.append("  :root{")
for k, v in ICONS.items():
    L.append('    --ic-%s:url("data:image/svg+xml,%s");' % (k, enc(v)))
L.append("  }")
L.append("  .ic{display:inline-block;width:1em;height:1em;flex-shrink:0;vertical-align:-.14em;")
L.append("    background:currentColor;-webkit-mask:var(--i) center/contain no-repeat;mask:var(--i) center/contain no-repeat}")
L.append("  " + "".join(".ic-%s{--i:var(--ic-%s)}" % (k, k) for k in ICONS))
out = "\n".join(L)
import os
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons.css"), "w", encoding="utf-8").write(out)
print("%d icons, %d chars" % (len(ICONS), len(out)))
