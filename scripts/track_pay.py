#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
track_pay.py —— 商户资料新旧两版字段级差异追踪

输入：merchants_old.csv（旧版）、merchants_new.csv（新版）
      字段：商户号,名称,费率,结算账户,状态,提交时间,生效时间
输出：
  changes.csv   变更流（首行为排序说明行，其后表头：商户号,变更字段,旧值,新值）
  additions.csv 新增登记（表头：商户号,名称,生效时间）
  closures.csv  注销登记（表头：商户号,名称,生效时间）
  summary.csv   汇总（表头：商户号,变更字段数）

口径：
  1. 费率：旧版记千分数值、新版记小数。本数据集旧版存在两种写法——
     >=1 的为千分数值（如 5 表示 5‰），<1 的本身已是小数。
     统一归一为小数：旧版 >=1 的值除以 1000，其余原样；新版原样。
     比较与输出均使用归一后的小数字符串，避免记法差异被误判为变更。
  2. 变更时间轴取各商户新版记录的【生效时间】（渠道侧真正生效的时间）；
     生效时间早于提交时间的回溯生效仍按生效时间排序。
  3. 新增/注销只按商户号是否在两版中出现判定；同号改名属于名称字段变更。
  4. summary 覆盖两版共有的全部商户（无变更者变更字段数记 0）。
"""

import argparse
import csv
import os
import sys

KEY = "商户号"
FIELDS = ["名称", "费率", "结算账户", "状态", "提交时间", "生效时间"]
HEADER = ["商户号", "名称", "费率", "结算账户", "状态", "提交时间", "生效时间"]

SORT_NOTE = (
    "排序说明：变更流按时间轴升序排列，时间轴取每条变更所属商户新版资料的生效时间"
    "（渠道侧实际生效时间，非运营提交时间；生效时间早于提交时间的回溯生效仍以生效时间为准）；"
    "同一时间点先按商户号升序、再按变更字段在表头中的顺序"
    "（名称、费率、结算账户、状态、提交时间、生效时间）排序。"
    "费率列均为归一化小数：旧版千分数值（值>=1）已除以1000转换，<1的原值本身即小数，与新版口径一致。"
)


def load(path):
    """读取一份商户资料，返回 {商户号: {字段: 字符串值}}。"""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != HEADER:
            raise ValueError("文件 %s 表头与预期不一致：%r" % (path, reader.fieldnames))
        rows = {}
        for raw in reader:
            row = {k: (raw[k].strip() if raw[k] is not None else "") for k in HEADER}
            mid = row[KEY]
            if mid in rows:
                raise ValueError("文件 %s 中商户号重复：%s" % (path, mid))
            rows[mid] = row
        return rows


def norm_rate(text):
    """费率归一为小数字符串。旧版 >=1 视为千分数值除以 1000，其余与新版均按小数。"""
    value = float(text)
    if value >= 1.0:
        value = value / 1000.0
    return str(value)


def field_values(row):
    """取一行参与比较的（显示值、比较值），费率做归一。"""
    display, compare = {}, {}
    for name in FIELDS:
        text = row[name]
        if name == "费率":
            display[name] = norm_rate(text)
            compare[name] = float(display[name])
        else:
            display[name] = text
            compare[name] = text
    return display, compare


def write_csv(path, header, rows, leading_note=None):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if leading_note is not None:
            writer.writerow([leading_note])
        writer.writerow(header)
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description="商户资料新旧两版字段级差异追踪")
    ap.add_argument("--old", required=True, help="旧版 merchants_old.csv 路径")
    ap.add_argument("--new", required=True, help="新版 merchants_new.csv 路径")
    ap.add_argument("--outdir", required=True, help="输出目录")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    old = load(args.old)
    new = load(args.new)

    old_ids, new_ids = set(old), set(new)
    common = sorted(old_ids & new_ids)
    added_ids = sorted(new_ids - old_ids)      # 新版有、旧版无：新增
    closed_ids = sorted(old_ids - new_ids)     # 旧版有、新版无：注销

    # ---- 字段级变更 ----
    changes = []        # (生效时间, 商户号, 字段序号, 变更字段, 旧值, 新值)
    change_count = {}   # 商户号 -> 变更字段数
    for mid in common:
        old_disp, old_cmp = field_values(old[mid])
        new_disp, new_cmp = field_values(new[mid])
        per = 0
        for idx, name in enumerate(FIELDS):
            if old_cmp[name] != new_cmp[name]:
                changes.append((
                    new[mid]["生效时间"], mid, idx, name,
                    old_disp[name], new_disp[name],
                ))
                per += 1
        change_count[mid] = per

    # 时间轴：新版生效时间 → 商户号 → 字段在表头中的顺序
    changes.sort(key=lambda c: (c[0], c[1], c[2]))
    change_rows = [[mid, name, ov, nv] for _, mid, _, name, ov, nv in changes]

    # ---- 新增 / 注销登记（均按生效时间、再按商户号排序）----
    additions = [
        [mid, new[mid]["名称"], new[mid]["生效时间"]]
        for mid in sorted(added_ids, key=lambda m: (new[m]["生效时间"], m))
    ]
    closures = [
        [mid, old[mid]["名称"], old[mid]["生效时间"]]
        for mid in sorted(closed_ids, key=lambda m: (old[m]["生效时间"], m))
    ]

    # ---- 汇总：覆盖两版共有的全部商户，按商户号排序 ----
    summary_rows = [[mid, change_count[mid]] for mid in common]

    # ---- 三方一致性校验 ----
    total_change_rows = len(change_rows)
    assert sum(change_count.values()) == total_change_rows, \
        "汇总变更字段数与变更流行数不一致"
    assert len(old) == len(common) + len(closures), "旧版商户数对不上"
    assert len(new) == len(common) + len(additions), "新版商户数对不上"
    assert len(summary_rows) == len(common), "汇总户数与共有商户数不一致"

    write_csv(os.path.join(args.outdir, "changes.csv"),
              ["商户号", "变更字段", "旧值", "新值"],
              change_rows, leading_note=SORT_NOTE)
    write_csv(os.path.join(args.outdir, "additions.csv"),
              ["商户号", "名称", "生效时间"], additions)
    write_csv(os.path.join(args.outdir, "closures.csv"),
              ["商户号", "名称", "生效时间"], closures)
    write_csv(os.path.join(args.outdir, "summary.csv"),
              ["商户号", "变更字段数"], summary_rows)

    print("旧版商户数: %d" % len(old))
    print("新版商户数: %d" % len(new))
    print("共有商户数(summary 行数): %d" % len(common))
    print("新增(additions 行数): %d" % len(additions))
    print("注销(closures 行数): %d" % len(closures))
    print("变更流总行数: %d" % total_change_rows)
    print("汇总变更字段数合计: %d" % sum(change_count.values()))
    print("无变更商户数: %d" % sum(1 for v in change_count.values() if v == 0))
    print("三方校验: 旧 %d = 共有 %d + 注销 %d；新 %d = 共有 %d + 新增 %d"
          % (len(old), len(common), len(closures),
             len(new), len(common), len(additions)))


if __name__ == "__main__":
    sys.exit(main())
