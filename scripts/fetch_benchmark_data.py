"""下载公开中文垃圾/诈骗短信数据集，分层采样出固定的 benchmark 样本。

数据源：hrwhisper/SpamMessage（GitHub），data/带标签短信.txt，约 80 万条，
格式为每行 "label\ttext"，label=1 为垃圾短信（广告/诈骗/钓鱼），label=0 为正常短信。
该仓库未声明 license，因此本仓库只提交派生的小样本（含出处与行号），
完整原始文件缓存在 data/benchmarks/（已 gitignore），由本脚本按固定 commit SHA 重新下载。

用法：
    python scripts/fetch_benchmark_data.py                  # 默认 300/类，其中 50/类 作 dev
    python scripts/fetch_benchmark_data.py --force          # 强制重新下载原始文件

输出（提交入库，~100KB）：
    evals/data/spam_sample_v1.jsonl       test 集（默认 250/类 × 2 = 500 条）
    evals/data/spam_sample_v1.dev.jsonl   dev 集（默认 50/类 × 2 = 100 条，只用于调阈值）
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 固定到具体 commit，保证可复现（git ls-remote 取得，2026-06-10）
COMMIT_SHA = "754d3a74c626770a8812b62563ae457832242ea1"
SOURCE_REPO = "hrwhisper/SpamMessage"
# data/带标签短信.txt 的 URL 编码
RAW_URL = (
    f"https://raw.githubusercontent.com/{SOURCE_REPO}/{COMMIT_SHA}/"
    "data/%E5%B8%A6%E6%A0%87%E7%AD%BE%E7%9F%AD%E4%BF%A1.txt"
)

CACHE_PATH = PROJECT_ROOT / "data" / "benchmarks" / "spam_message_full.txt"
OUT_DIR = PROJECT_ROOT / "evals" / "data"
TEST_PATH = OUT_DIR / "spam_sample_v1.jsonl"
DEV_PATH = OUT_DIR / "spam_sample_v1.dev.jsonl"

MIN_TEXT_LEN = 8


def download(force: bool = False) -> Path:
    """下载完整原始文件到本地缓存（~58MB），已存在则跳过。"""
    if CACHE_PATH.exists() and not force:
        print(f"[fetch] 缓存已存在，跳过下载: {CACHE_PATH} ({CACHE_PATH.stat().st_size} bytes)")
        return CACHE_PATH

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"[fetch] 下载 {SOURCE_REPO}@{COMMIT_SHA[:7]} ...")
    with requests.get(RAW_URL, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        tmp = CACHE_PATH.with_suffix(".part")
        done = 0
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                done += len(chunk)
                print(f"\r[fetch] 已下载 {done / 1e6:.1f} MB", end="")
        print()
        tmp.replace(CACHE_PATH)
    print(f"[fetch] 完成: {CACHE_PATH} ({CACHE_PATH.stat().st_size} bytes)")
    return CACHE_PATH


def _read_text(path: Path) -> list[str]:
    """读原始文件为行列表。优先 UTF-8，若疑似乱码则退回 GBK。"""
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    probe = text[:200_000]
    if probe.count("�") > len(probe) * 0.01:
        text = raw.decode("gbk", errors="replace")
    return text.splitlines()


def parse_lines(path: Path) -> list[tuple[int, int, str]]:
    """解析为 (原始行号, label, text)，跳过格式错误行。"""
    rows: list[tuple[int, int, str]] = []
    bad = 0
    for line_no, line in enumerate(_read_text(path), start=1):
        parts = line.split("\t", 1)
        if len(parts) != 2 or parts[0] not in ("0", "1"):
            bad += 1
            continue
        text = parts[1].strip()
        if "�" in text:
            bad += 1
            continue
        rows.append((line_no, int(parts[0]), text))
    print(f"[parse] 有效 {len(rows)} 行，跳过格式错误/乱码 {bad} 行")
    return rows


def clean(rows: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """去重（按文本精确匹配，保留首次出现）+ 过滤过短文本。"""
    seen: set[str] = set()
    out: list[tuple[int, int, str]] = []
    dropped_short = dropped_dup = 0
    for line_no, label, text in rows:
        if len(text) < MIN_TEXT_LEN:
            dropped_short += 1
            continue
        if text in seen:
            dropped_dup += 1
            continue
        seen.add(text)
        out.append((line_no, label, text))
    print(f"[clean] 保留 {len(out)} 行（去短文本 {dropped_short}，去重 {dropped_dup}）")
    return out


def stratified_sample(
    rows: list[tuple[int, int, str]], n_per_class: int, seed: int = 42
) -> list[dict]:
    """每类抽 n_per_class 条，固定种子保证可复现。"""
    rng = random.Random(seed)
    samples: list[dict] = []
    for label in (0, 1):
        pool = [r for r in rows if r[1] == label]
        if len(pool) < n_per_class:
            raise SystemExit(f"类别 {label} 仅 {len(pool)} 条，不足 {n_per_class}")
        picked = rng.sample(pool, n_per_class)
        for line_no, lab, text in picked:
            samples.append({
                "id": f"sms-{line_no}",
                "text": text,
                "label": lab,
                "source": f"{SOURCE_REPO}@{COMMIT_SHA[:7]}",
                "line_no": line_no,
            })
    return samples


def split_dev_test(samples: list[dict], dev_per_class: int, seed: int = 42) -> tuple[list[dict], list[dict]]:
    """每类前 dev_per_class 条进 dev（shuffle 后切分），其余进 test。"""
    rng = random.Random(seed + 1)
    dev: list[dict] = []
    test: list[dict] = []
    for label in (0, 1):
        group = [s for s in samples if s["label"] == label]
        rng.shuffle(group)
        dev.extend(group[:dev_per_class])
        test.extend(group[dev_per_class:])
    key = lambda s: s["line_no"]  # noqa: E731 — 按原始行号排序，输出稳定
    return sorted(dev, key=key), sorted(test, key=key)


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[write] {path}（{len(records)} 条）")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-per-class", type=int, default=300)
    parser.add_argument("--dev-per-class", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true", help="强制重新下载原始文件")
    args = parser.parse_args()

    path = download(force=args.force)
    rows = clean(parse_lines(path))

    n_spam = sum(1 for r in rows if r[1] == 1)
    print(f"[stats] 正常 {len(rows) - n_spam} / 垃圾 {n_spam}")

    samples = stratified_sample(rows, args.n_per_class, seed=args.seed)
    dev, test = split_dev_test(samples, args.dev_per_class, seed=args.seed)
    write_jsonl(DEV_PATH, dev)
    write_jsonl(TEST_PATH, test)
    print(f"[done] dev {len(dev)} 条 / test {len(test)} 条，seed={args.seed}，源 {SOURCE_REPO}@{COMMIT_SHA[:7]}")


if __name__ == "__main__":
    main()
