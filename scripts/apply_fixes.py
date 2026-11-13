#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对官方代码应用三处兼容性修复。

原仓库 https://github.com/DeepGraphLearning/KnowledgeGraphEmbedding (MIT)
发布于 2019 年，在 NumPy 2.x + Windows 环境下无法直接运行。
本脚本以文本替换方式应用修复，可重复执行（幂等）。

用法:
    python scripts/apply_fixes.py --repo ./KnowledgeGraphEmbedding
"""

import argparse
import re
import sys
import time
from pathlib import Path


def write_safe(path: Path, text: str) -> None:
    """写入文本。Windows 上杀毒软件可能短暂锁定刚修改的文件，失败后重试一次。"""
    try:
        path.write_text(text, encoding="utf-8")
    except PermissionError:
        time.sleep(1.0)
        path.write_text(text, encoding="utf-8")


def patch_dataloader(path: Path) -> str:
    """NumPy 2.0 移除了 np.in1d，改为 np.isin（参数签名一致）。"""
    text = path.read_text(encoding="utf-8")
    if "np.isin(" in text and "np.in1d(" not in text:
        return "skip（已是 np.isin）"
    if "np.in1d(" not in text:
        return "skip（未找到 np.in1d，可能代码版本不同）"
    n = text.count("np.in1d(")
    write_safe(path, text.replace("np.in1d(", "np.isin("))
    return f"ok（替换 {n} 处）"


def patch_run_seed(path: Path) -> str:
    """原代码没有随机种子控制，新增 --seed 参数并在入口处固定。"""
    text = path.read_text(encoding="utf-8")
    if "--seed" in text:
        return "skip（已应用）"

    # 1) 注册命令行参数
    anchor = "    parser.add_argument('--cuda', action='store_true', help='use GPU')\n"
    if anchor not in text:
        return "fail（未找到 --cuda 参数定义）"
    arg_block = (
        anchor
        + "\n    # 复现补丁：原代码没有随机种子控制，导致同一配置每次结果不同\n"
        + "    parser.add_argument('--seed', default=0, type=int,\n"
        + "                        help='random seed for reproducibility')\n"
    )
    text = text.replace(anchor, arg_block, 1)

    # 2) 在 main() 开头设置种子
    main_anchor = "def main(args):\n"
    if main_anchor not in text:
        return "fail（未找到 main 函数）"
    seed_block = (
        main_anchor
        + "    # 复现补丁：固定随机种子\n"
        + "    random.seed(args.seed)\n"
        + "    np.random.seed(args.seed)\n"
        + "    torch.manual_seed(args.seed)\n"
        + "    if torch.cuda.is_available():\n"
        + "        torch.cuda.manual_seed_all(args.seed)\n"
        + "    torch.backends.cudnn.deterministic = True\n"
        + "    torch.backends.cudnn.benchmark = False\n"
        + "\n"
    )
    text = text.replace(main_anchor, seed_block, 1)

    # 3) 日志初始化之后再记录种子值
    #    注意：不能在 set_logger() 之前调用 logging.info()，
    #    否则会提前触发 basicConfig()，使得 set_logger() 里的
    #    basicConfig(filename=...) 失效，导致日志文件不会生成。
    log_anchor = "    # Write logs to checkpoint and console\n    set_logger(args)\n"
    if log_anchor in text:
        text = text.replace(
            log_anchor,
            log_anchor + "    logging.info('Random seed fixed to %d' % args.seed)\n",
            1,
        )

    write_safe(path, text)
    return "ok（新增 --seed 参数并固定四种随机源）"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="./KnowledgeGraphEmbedding",
                    help="官方仓库根目录")
    args = ap.parse_args()

    repo = Path(args.repo)
    if not (repo / "codes" / "run.py").exists():
        print(f"[错误] 未在 {repo} 下找到 codes/run.py", file=sys.stderr)
        sys.exit(1)

    targets = [
        ("codes/dataloader.py", patch_dataloader),
        ("codes/run.py", patch_run_seed),
    ]
    print(f"目标仓库: {repo.resolve()}")
    for rel, fn in targets:
        p = repo / rel
        if not p.exists():
            print(f"  {rel:<22} fail（文件不存在）")
            continue
        print(f"  {rel:<22} {fn(p)}")
    print("\n完成。可用 `git diff` 查看具体改动。")


if __name__ == "__main__":
    main()
