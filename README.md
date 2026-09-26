# extract_shots

拉片用的镜头切点关键帧提取工具。基于 `ffmpeg` 的 `scene` 滤镜检测视频中的镜头切换点（硬切 / 渐变），并自动导出每个镜头的入点帧与出点帧，同时生成一份镜头表（`index.csv`）。

## 环境要求

- Python 3.x
- 本仓库自带的 `ffmpeg-win-x86_64-v7.1.exe`（Windows 版，已内置，无需另行安装）

## 用法

```bash
python extract_shots.py <video> [--out DIR] [--th 0.25] [--gap 0.4] [--weak-th 0.15]
```

### 参数说明

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `video` | （必填） | 待分析的视频文件 |
| `--out` | `shots` | 输出目录 |
| `--th` | `0.25` | 硬切阈值（分数 ≥ 此值判定为「硬切」，否则为「疑似/渐变」） |
| `--gap` | `0.4` | 相邻切点的最小时间间隔（秒），避免过密 |
| `--weak-th` | `0.15` | 候选帧阈值，分数高于此值才会被导出为候选切点 |

## 输出

默认输出到 `shots/` 目录：

- `shot_NNN_IN_MMmSSs.jpg`：每个镜头的入点帧（切点帧）
- `shot_NNN_OUT_MMmSSs.jpg`：每个镜头的出点帧（切点前一帧）
- `index.csv`：镜头表，字段为 `镜号 / 入点(秒) / 出点(秒) / 时长(秒) / 切点分数 / 判定 / 入点帧 / 出点帧`

## 工作流程

1. 探测视频时长。
2. 用 `scene` 滤镜计算全片每个时间点的镜头变化分数。
3. 按 `weak-th` 导出候选切点帧，再以 `th` + `gap` 贪心筛选局部峰值作为最终切点。
4. 复用候选帧作为入点帧，并额外抓取每个镜头出点前 `0.1s` 的帧作为出点帧。
5. 写出镜头表 `index.csv`，并清理临时候选图。

## 示例

```bash
python extract_shots.py movie.mp4
python extract_shots.py movie.mp4 --out results --th 0.3 --gap 0.5
```
