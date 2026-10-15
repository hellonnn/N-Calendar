#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成节假日数据（holidays.json 与 index.html 里的内置表）

数据来源：中国政府网公布的国务院办公厅通知原文
  2024 国办发明电〔2023〕7号  https://www.gov.cn/gongbao/2023/issue_10806/202311/content_6913823.html
  2025 国办发明电〔2024〕12号 http://big5.www.gov.cn/gate/big5/www.gov.cn/gongbao/2024/issue_11726/202411/content_6989767.html
  2026 国办发明电〔2025〕7号  https://www.gov.cn/zhengce/content/202511/content_7047090.htm

以后每年新通知发布后，把新的 range/work 加进下面，然后：
    python3 tools/make-holidays.py            # 重新生成 ../holidays.json
    python3 tools/make-holidays.py --js       # 打印供粘贴进 index.html 的内置表
"""
import datetime
import json
import os
import sys

D = datetime.date

# 每年：放假区间（起, 止, 名称）与调休上班日
YEARS = {
    "2024": {
        "source": "国办发明电〔2023〕7号",
        "url": "https://www.gov.cn/gongbao/2023/issue_10806/202311/content_6913823.html",
        "ranges": [
            (D(2024, 1, 1), D(2024, 1, 1), "元旦"),
            (D(2024, 2, 10), D(2024, 2, 17), "春节"),
            (D(2024, 4, 4), D(2024, 4, 6), "清明节"),
            (D(2024, 5, 1), D(2024, 5, 5), "劳动节"),
            (D(2024, 6, 10), D(2024, 6, 10), "端午节"),
            (D(2024, 9, 15), D(2024, 9, 17), "中秋节"),
            (D(2024, 10, 1), D(2024, 10, 7), "国庆节"),
        ],
        "work": [D(2024, 2, 4), D(2024, 2, 18), D(2024, 4, 7), D(2024, 4, 28),
                 D(2024, 5, 11), D(2024, 9, 14), D(2024, 9, 29), D(2024, 10, 12)],
    },
    "2025": {
        "source": "国办发明电〔2024〕12号",
        "url": "http://big5.www.gov.cn/gate/big5/www.gov.cn/gongbao/2024/issue_11726/202411/content_6989767.html",
        "ranges": [
            (D(2025, 1, 1), D(2025, 1, 1), "元旦"),
            (D(2025, 1, 28), D(2025, 2, 4), "春节"),
            (D(2025, 4, 4), D(2025, 4, 6), "清明节"),
            (D(2025, 5, 1), D(2025, 5, 5), "劳动节"),
            (D(2025, 5, 31), D(2025, 6, 2), "端午节"),
            (D(2025, 10, 1), D(2025, 10, 8), "国庆节·中秋节"),
        ],
        "work": [D(2025, 1, 26), D(2025, 2, 8), D(2025, 4, 27), D(2025, 9, 28), D(2025, 10, 11)],
    },
    "2026": {
        "source": "国办发明电〔2025〕7号",
        "url": "https://www.gov.cn/zhengce/content/202511/content_7047090.htm",
        "ranges": [
            (D(2026, 1, 1), D(2026, 1, 3), "元旦"),
            (D(2026, 2, 15), D(2026, 2, 23), "春节"),
            (D(2026, 4, 4), D(2026, 4, 6), "清明节"),
            (D(2026, 5, 1), D(2026, 5, 5), "劳动节"),
            (D(2026, 6, 19), D(2026, 6, 21), "端午节"),
            (D(2026, 9, 25), D(2026, 9, 27), "中秋节"),
            (D(2026, 10, 1), D(2026, 10, 7), "国庆节"),
        ],
        "work": [D(2026, 1, 4), D(2026, 2, 14), D(2026, 2, 28),
                 D(2026, 5, 9), D(2026, 9, 20), D(2026, 10, 10)],
    },
}


def build():
    out = {}
    for year, cfg in YEARS.items():
        off = {}
        for start, end, name in cfg["ranges"]:
            day = start
            while day <= end:
                off[day.isoformat()] = name
                day += datetime.timedelta(days=1)
        work = {d.isoformat(): "补班" for d in cfg["work"]}
        out[year] = {"source": cfg["source"], "url": cfg["url"], "off": off, "work": work}
    return out


def main():
    data = build()
    if "--js" in sys.argv:
        print("const HOLIDAY_BUILTIN = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";")
        return
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(os.path.dirname(here), "holidays.json")
    doc = {
        "version": "2024-2026",
        "note": "工作日/节假日数据。off = 放假，work = 调休上班。可用 tools/make-holidays.py 重新生成。",
        "updated": max(d for y in YEARS.values() for r in y["ranges"] for d in (r[0], r[1])).isoformat(),
        "years": data,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    n_off = sum(len(v["off"]) for v in data.values())
    n_work = sum(len(v["work"]) for v in data.values())
    print("已生成 %s：%d 个年份，放假 %d 天，调休上班 %d 天" % (path, len(data), n_off, n_work))


if __name__ == "__main__":
    main()
