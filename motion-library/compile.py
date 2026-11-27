#!/usr/bin/env python3
"""CLI for compiling a motion JSON file to CSS."""

import argparse
import pathlib
from compiler import compile_css, load_spec


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("spec")
    parser.add_argument("--output")
    args = parser.parse_args()
    css = compile_css(load_spec(args.spec))
    if args.output:
        pathlib.Path(args.output).write_text(css, encoding="utf-8")
    else:
        print(css, end="")


if __name__ == "__main__":
    main()
